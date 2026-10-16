import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import avl4_import
from flowsint_core.avl4_import.contracts import (
    IMPORT_PATH,
    MAX_BODY_BYTES,
    CardImportCommand,
    CardSnapshot,
)
from flowsint_core.avl4_import.signing import signature
from flowsint_core.core.models import Base, Investigation, Sketch
from flowsint_core.core.platform_auth import AccessDenied
from flowsint_core.core.project_scope import ProjectScope, current_scope, project_scope

KEY = "test-import-signing-key-at-least-32-characters"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        yield db
    engine.dispose()


@pytest.fixture
def import_setup(db_session, monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    monkeypatch.setenv("FLOWSINT_CARDS_IMPORT_KEY", KEY)
    monkeypatch.setenv("FLOWSINT_UI_BASE_URL", "https://flowsint.test")
    checks = []

    def verify(user, project, private=None):
        checks.append((user, project, private))
        if user == "revoked":
            raise AccessDenied

    monkeypatch.setattr(avl4_import, "verify_actor_sync", verify)
    monkeypatch.setattr("flowsint_core.core.platform_auth.verify_actor_sync", verify)

    class Graph:
        calls = 0

        def project(self, material):
            self.calls += 1
            return "element:material"

    graph = Graph()
    from app.main import app

    app.dependency_overrides[avl4_import.get_import_graph] = lambda: graph
    with project_scope(ProjectScope("alice", "project-a")):
        inv = Investigation(id=uuid4(), name="Case")
        sketch = Sketch(id=uuid4(), title="Graph", investigation_id=inv.id)
        db_session.add_all([inv, sketch])
        db_session.commit()
        inv_id, sketch_id = inv.id, sketch.id
    now = datetime.now(timezone.utc)
    command = CardImportCommand(
        operation_id=uuid4(),
        actor_id="alice",
        project_id="project-a",
        investigation_id=inv_id,
        sketch_id=sketch_id,
        snapshot=CardSnapshot(
            card_id="card-1",
            card_type="shared",
            title="A",
            markdown="Snapshot",
            monitoring_url="https://monitoring.test/feed?cardId=card-1",
            published_at=now,
            source_updated_at=now,
            captured_at=now,
        ),
    )
    yield command, graph, checks
    app.dependency_overrides.pop(avl4_import.get_import_graph, None)


def signed(command, timestamp=None):
    body = command.model_dump_json().encode()
    stamp = str(timestamp or int(time.time()))
    return body, {
        "Content-Type": "application/json",
        "h-avl-cards-timestamp": stamp,
        "h-avl-cards-signature": signature(KEY, body, stamp),
    }


def test_internal_import_requires_service_proof_not_session_or_bearer(
    client, import_setup
):
    command, graph, _ = import_setup
    response = client.post(
        IMPORT_PATH,
        json=command.model_dump(mode="json"),
        headers={"h-avl-session": "alice", "Authorization": "Bearer forged"},
    )
    assert response.status_code == 401
    assert "X-AVL-Auth-Guard" not in response.headers
    assert graph.calls == 0


@pytest.mark.parametrize(
    "failure",
    [
        "tampered",
        "expired",
        "future",
        "unicode",
        "version",
        "unknown",
        "project",
        "oversized",
    ],
)
def test_invalid_signed_requests_cannot_write(client, import_setup, failure):
    command, graph, _ = import_setup
    body, headers = signed(command)
    expected = 401
    if failure == "tampered":
        body += b" "
    if failure in {"expired", "future"}:
        body, headers = signed(
            command, int(time.time()) + (600 if failure == "future" else -600)
        )
    if failure == "unicode":
        headers["h-avl-cards-signature"] = "!" * 64
    if failure in {"version", "unknown", "project"}:
        data = command.model_dump(mode="json")
        if failure == "version":
            data["version"] = 2
        if failure == "unknown":
            data["untrusted_user"] = "admin"
        if failure == "project":
            data["snapshot"]["card_type"] = "project"
            data["snapshot"]["source_project_id"] = "foreign"
        import json

        body = json.dumps(data).encode()
        headers["h-avl-cards-signature"] = signature(
            KEY, body, headers["h-avl-cards-timestamp"]
        )
        expected = 422
    if failure == "oversized":
        body = b"x" * (MAX_BODY_BYTES + 1)
        expected = 413
    assert (
        client.post(IMPORT_PATH, content=body, headers=headers).status_code == expected
    )
    assert graph.calls == 0


def test_verified_import_and_retry_revalidate_actor_and_restore_context(
    client, import_setup
):
    command, graph, checks = import_setup
    body, headers = signed(command)
    response = client.post(IMPORT_PATH, content=body, headers=headers)
    assert response.status_code == 200, response.text
    assert (
        client.post(IMPORT_PATH, content=body, headers=headers).json()
        == response.json()
    )
    assert graph.calls == 1
    assert len(checks) >= 2
    assert current_scope() is None
    revoked = command.model_copy(
        update={"actor_id": "revoked", "operation_id": uuid4()}
    )
    body, headers = signed(revoked)
    assert client.post(IMPORT_PATH, content=body, headers=headers).status_code == 403
    assert graph.calls == 1


def test_import_target_must_belong_to_selected_project(client, import_setup):
    command, graph, _ = import_setup
    body, headers = signed(command.model_copy(update={"project_id": "foreign"}))
    response = client.post(IMPORT_PATH, content=body, headers=headers)
    assert response.status_code == 404
    assert graph.calls == 0


def test_internal_import_unavailable_in_standalone(client, import_setup, monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "standalone")
    command, graph, _ = import_setup
    body, headers = signed(command)
    assert client.post(IMPORT_PATH, content=body, headers=headers).status_code == 404
    assert graph.calls == 0


def test_completed_operation_is_not_an_authorization_bypass(
    client, import_setup, monkeypatch
):
    command, graph, _ = import_setup
    body, headers = signed(command)
    assert client.post(IMPORT_PATH, content=body, headers=headers).status_code == 200

    def deny(*_):
        raise AccessDenied

    monkeypatch.setattr(avl4_import, "verify_actor_sync", deny)
    assert client.post(IMPORT_PATH, content=body, headers=headers).status_code == 403
    assert graph.calls == 1
