"""HTTP boundaries using opaque Auth user/project IDs and no local Profiles."""

import asyncio

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from flowsint_core.core.models import Base
from flowsint_core.core.platform_auth import AccessDenied, AuthClient, SessionRejected
from flowsint_core.core.project_scope import ProjectScope


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def platform(monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")

    async def authenticate(self, session_id, project_id):
        if session_id == "unavailable":
            raise ConnectionError("private connection detail")
        if session_id not in {"alice", "bob"}:
            raise SessionRejected
        if project_id not in {"project-a", "project-b"}:
            raise AccessDenied
        return ProjectScope(user_id=session_id, project_id=project_id)

    monkeypatch.setattr(AuthClient, "authenticate", authenticate)


def headers(user="alice", project="project-a"):
    return {"h-avl-session": user, "h-avl-project": project}


def test_bearer_or_forged_user_header_cannot_replace_avl4_session(client):
    response = client.get(
        "/api/investigations",
        headers={
            "Authorization": "Bearer forged",
            "h-avl-user": "alice",
            "h-avl-project": "project-a",
        },
    )
    assert response.status_code == 401
    assert response.headers["X-AVL-Auth-Guard"] == "session-rejected"


def test_missing_project_and_denied_project_are_distinct_from_session_loss(client):
    assert (
        client.get(
            "/api/investigations", headers={"h-avl-session": "alice"}
        ).status_code
        == 400
    )
    response = client.get("/api/investigations", headers=headers(project="forbidden"))
    assert response.status_code == 403
    assert "X-AVL-Auth-Guard" not in response.headers


def test_auth_outage_is_503_without_private_details_or_logout_marker(client):
    response = client.get("/api/investigations", headers=headers(user="unavailable"))
    assert response.status_code == 503
    assert response.json() == {"detail": "AUTH_UNAVAILABLE"}
    assert "X-AVL-Auth-Guard" not in response.headers


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/auth/token", "post"),
        ("/api/auth/register", "post"),
        ("/api/auth/users/search?q=x", "get"),
        ("/api/auth/me", "put"),
        ("/api/investigations/example/collaborators", "get"),
    ],
)
def test_local_accounts_and_collaborator_management_disabled(client, path, method):
    assert getattr(client, method)(path, headers=headers()).status_code == 404


def test_opaque_auth_identity_and_project_wide_investigation_access(client):
    response = client.post(
        "/api/investigations/create",
        headers=headers(),
        json={
            "name": "Case",
            "description": "Description",
        },
    )
    assert response.status_code == 201, response.text
    inv = response.json()
    assert inv["project_id"] == "project-a"
    assert inv["created_by"] == "alice"
    assert inv["owner_id"] is None
    assert inv["current_user_role"] is None
    response = client.get("/api/investigations", headers=headers("bob"))
    assert [i["id"] for i in response.json()] == [inv["id"]]
    assert (
        client.get("/api/investigations", headers=headers(project="project-b")).json()
        == []
    )
    assert (
        client.get(
            f"/api/investigations/{inv['id']}", headers=headers(project="project-b")
        ).status_code
        == 403
    )
    me = client.get("/api/auth/me", headers=headers("bob"))
    assert me.status_code == 200
    assert me.json()["id"] == "bob"


def test_cookie_mutation_requires_allowed_origin(client):
    client.cookies.set("c-avl-session", "alice")
    response = client.post(
        "/api/investigations/create",
        headers={
            "h-avl-project": "project-a",
            "origin": "https://attacker.invalid",
        },
        json={"name": "Case", "description": "Description"},
    )
    assert response.status_code == 403


def test_cookie_session_and_allowed_origin_work(client):
    client.cookies.set("c-avl-session", "alice")
    response = client.post(
        "/api/investigations/create",
        headers={
            "h-avl-project": "project-a",
            "origin": "http://localhost:5173",
        },
        json={"name": "Case", "description": "Description"},
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "create_path,list_path,payload",
    [
        ("/api/keys/create", "/api/keys", {"name": "SHARED_KEY", "key": "test-secret"}),
        (
            "/api/flows/create",
            "/api/flows",
            {
                "name": "Shared flow",
                "category": [],
                "flow_schema": {},
            },
        ),
        ("/api/chats/create", "/api/chats", {"title": "Shared chat"}),
        (
            "/api/custom-types",
            "/api/custom-types",
            {
                "name": "SharedType",
                "schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
            },
        ),
        (
            "/api/enrichers/templates",
            "/api/enrichers/templates",
            {
                "name": "lookup",
                "category": "Domain",
                "version": 1.0,
                "is_public": True,
                "content": {
                    "name": "lookup",
                    "category": "Domain",
                    "version": 1.0,
                    "input": {"type": "Domain"},
                    "request": {"method": "GET", "url": "https://example.com"},
                    "output": {"type": "Domain"},
                    "response": {"expect": "json"},
                },
            },
        ),
    ],
)
def test_project_members_share_all_resource_types_and_other_projects_cannot_read_them(
    client,
    create_path,
    list_path,
    payload,
):
    response = client.post(create_path, headers=headers(), json=payload)
    assert response.status_code == 201, response.text
    resource_id = response.json()["id"]
    response = client.get(list_path, headers=headers("bob"))
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [resource_id]
    response = client.get(f"{list_path}/{resource_id}", headers=headers("bob"))
    assert response.status_code == 200, response.text
    response = client.get(list_path, headers=headers(project="project-b"))
    assert response.json() == [], response.text
    response = client.get(
        f"{list_path}/{resource_id}", headers=headers(project="project-b")
    )
    assert response.status_code == 404, response.text
    response = client.delete(f"{list_path}/{resource_id}", headers=headers("bob"))
    assert response.status_code == 204, response.text


def test_other_project_cannot_reach_graph_or_enqueue_a_known_sketch(
    client, monkeypatch, db_session
):
    from uuid import UUID, uuid4

    from app.api.routes import enrichers
    from flowsint_core.core.models import Scan
    from flowsint_core.core.project_scope import project_scope
    from flowsint_core.core.services import sketch_service

    inv = client.post(
        "/api/investigations/create",
        headers=headers(),
        json={
            "name": "Case",
            "description": "Description",
        },
    ).json()
    response = client.post(
        "/api/sketches/create",
        headers=headers(),
        json={
            "title": "Graph",
            "description": "",
            "investigation_id": inv["id"],
        },
    )
    assert response.status_code == 201, response.text
    sketch_id = response.json()["id"]
    scan_id = uuid4()
    with project_scope(ProjectScope(user_id="alice", project_id="project-a")):
        db_session.add(Scan(id=scan_id, sketch_id=UUID(sketch_id)))
        db_session.commit()

    def forbidden_call(*args, **kwargs):
        pytest.fail("Foreign sketch reached graph or broker")

    monkeypatch.setattr(sketch_service, "create_graph_service", forbidden_call)
    monkeypatch.setattr(enrichers.celery, "send_task", forbidden_call)
    response = client.get(
        f"/api/events/sketch/{sketch_id}/logs", headers=headers("bob")
    )
    assert response.status_code == 200, response.text
    assert response.json() == []
    other = headers(project="project-b")
    assert (
        client.get(f"/api/sketches/{sketch_id}/graph", headers=other).status_code == 404
    )
    response = client.post(
        "/api/enrichers/example/launch",
        headers=other,
        json={
            "node_ids": ["known-node"],
            "sketch_id": sketch_id,
        },
    )
    assert response.status_code == 404
    for path in [
        f"/api/sketches/{sketch_id}/export",
        f"/api/scans/{scan_id}",
        f"/api/events/sketch/{sketch_id}/logs",
        f"/api/events/sketch/{sketch_id}/stream",
        f"/api/events/sketch/{sketch_id}/status/stream",
    ]:
        response = client.get(path, headers=other)
        assert response.status_code == 404, (path, response.text)


def test_stream_revalidates_access_before_sending_more_project_data(monkeypatch):
    from app.security.platform import Avl4AuthMiddleware
    from flowsint_core.core.project_scope import current_scope

    calls = []

    async def authenticate(self, session_id, project_id):
        calls.append((session_id, project_id))
        if len(calls) > 1:
            raise AccessDenied
        return ProjectScope(user_id="alice", project_id="project-a")

    monkeypatch.setattr(AuthClient, "authenticate", authenticate)
    times = iter([0, 11])
    monkeypatch.setattr("app.security.platform.monotonic", lambda: next(times))
    messages = []

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"private data", "more_body": True}
        )

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    request = dict(
        type="http",
        method="GET",
        path="/api/events/stream",
        scheme="http",
        server=("testserver", 80),
        query_string=b"",
        headers=[
            (b"h-avl-session", b"alice"),
            (b"h-avl-project", b"project-a"),
        ],
    )
    with pytest.raises(OSError, match="admission ended"):
        asyncio.run(Avl4AuthMiddleware(app)(request, receive, send))
    assert len(calls) == 2
    assert all(m["type"] != "http.response.body" for m in messages)
    assert current_scope() is None
