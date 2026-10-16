"""Visibility changes must reach every catalog while respecting admin/project access."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from flowsint_core.core.auth import create_access_token
from flowsint_core.core.models import Base, EnricherTemplate, Profile
from flowsint_core.core.platform_auth import AuthClient
from flowsint_core.core.project_scope import ProjectScope, project_scope
from flowsint_enrichers import ENRICHER_REGISTRY

ADMIN = "/api/enrichers/administration"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


@pytest.fixture(autouse=True)
def standalone(monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "standalone")
    monkeypatch.delenv("FLOWSINT_ADMIN_USER_IDS", raising=False)


@pytest.fixture
def admin_headers(db_session, monkeypatch):
    user = Profile(id=uuid4(), email="admin@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    monkeypatch.setenv("FLOWSINT_ADMIN_USER_IDS", f" {user.id} ")
    return {"Authorization": f"Bearer {create_access_token({'sub': user.email})}"}


@pytest.fixture
def builtin():
    return next(e for e in ENRICHER_REGISTRY.list() if e["name"] != "n8n_connector")


def names(client, path, headers):
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    if path == "/api/flows/raw_materials":
        return {
            e["name"]
            for category, items in data["items"].items()
            if category != "types"
            for e in items
        }
    if isinstance(data, dict):
        data = data["items"]
    return {e["name"] for e in data}


def test_builtin_toggle_persists_and_filters_all_catalogs(
    client, db_session, admin_headers, builtin
):
    name = builtin["name"]
    paths = [
        "/api/enrichers",
        f"/api/enrichers?category={builtin['inputs']['type']}",
        "/api/flows/raw_materials",
        f"/api/flows/input_type/{builtin['inputs']['type']}",
    ]
    assert all(name in names(client, path, admin_headers) for path in paths)
    for visible in (False, True):
        response = client.patch(
            f"{ADMIN}/builtin/{name}",
            headers=admin_headers,
            json={"is_visible": visible},
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_visible"] is visible
        db_session.expire_all()
        admin_row = next(
            row
            for row in client.get(ADMIN, headers=admin_headers).json()
            if row["kind"] == "builtin" and row["id"] == name
        )
        assert admin_row["is_visible"] is visible
        assert all(
            (name in names(client, path, admin_headers)) == visible for path in paths
        )
    assert "types" in client.get(paths[2], headers=admin_headers).json()["items"]


def test_template_toggle_is_independent_of_sharing_and_builtin_with_same_name(
    client, db_session, admin_headers, builtin
):
    owner = db_session.query(Profile).one()
    template = EnricherTemplate(
        name=builtin["name"],
        category="Domain",
        owner_id=owner.id,
        content={
            "input": {"type": "Domain"},
            "output": {"type": "Ip"},
            "request": {"headers": {"Authorization": "private-value"}},
        },
        is_public=False,
    )
    db_session.add(template)
    db_session.commit()
    identifier = str(template.id)
    listing = client.get(ADMIN, headers=admin_headers)
    assert "private-value" not in listing.text
    assert "content" not in listing.json()[0]
    assert any(row["id"] == identifier for row in listing.json())
    for visible in (False, True):
        response = client.patch(
            f"{ADMIN}/template/{identifier}",
            headers=admin_headers,
            json={"is_visible": visible},
        )
        assert response.status_code == 200, response.text
        listed = client.get("/api/enrichers", headers=admin_headers).json()
        assert any(row.get("id") == identifier for row in listed) == visible
        assert any(
            row["name"] == builtin["name"] and not row.get("id") for row in listed
        )
        assert db_session.query(EnricherTemplate).one().is_public is False


def test_admin_catalog_includes_private_templates_of_other_owners(
    client, db_session, admin_headers
):
    stranger = Profile(id=uuid4(), email="other@example.com", hashed_password="x")
    template = EnricherTemplate(
        name="private-template", category="Domain", owner_id=stranger.id, content={}
    )
    db_session.add_all([stranger, template])
    db_session.commit()
    assert "private-template" not in names(client, "/api/enrichers", admin_headers)
    assert any(
        row["name"] == "private-template"
        for row in client.get(ADMIN, headers=admin_headers).json()
    )


def test_legacy_hidden_builtin_is_in_admin_table_and_can_be_restored(
    client, admin_headers
):
    listing = client.get(ADMIN, headers=admin_headers).json()
    row = next(
        row
        for row in listing
        if row["kind"] == "builtin" and row["id"] == "n8n_connector"
    )
    assert row["is_visible"] is False
    assert "n8n_connector" not in names(client, "/api/enrichers", admin_headers)
    response = client.patch(
        f"{ADMIN}/builtin/n8n_connector",
        headers=admin_headers,
        json={"is_visible": True},
    )
    assert response.status_code == 200
    assert "n8n_connector" in names(client, "/api/enrichers", admin_headers)


def test_public_metadata_is_consistent_in_admin_patch_and_launch_catalogs(
    client, admin_headers
):
    expected = {
        key: value
        for key, value in next(
            item for item in ENRICHER_REGISTRY.list() if item["name"] == "ip_to_ports"
        ).items()
        if key in {"description", "providers", "api_key_requirement", "api_key_notes"}
    }
    rows = [
        next(
            row
            for row in client.get(ADMIN, headers=admin_headers).json()
            if row["name"] == "ip_to_ports"
        )
    ]
    rows.append(
        client.patch(
            f"{ADMIN}/builtin/ip_to_ports",
            headers=admin_headers,
            json={"is_visible": True},
        ).json()
    )
    for path in ("/api/enrichers", "/api/flows/input_type/Ip"):
        response = client.get(path, headers=admin_headers)
        assert response.status_code == 200
        items = response.json()
        if isinstance(items, dict):
            items = items["items"]
        rows.append(next(row for row in items if row["name"] == "ip_to_ports"))
    raw = client.get("/api/flows/raw_materials", headers=admin_headers).json()["items"]
    rows.append(
        next(
            row
            for category, items in raw.items()
            if category != "types"
            for row in items
            if row["name"] == "ip_to_ports"
        )
    )
    for row in rows:
        assert {key: row[key] for key in expected} == expected


@pytest.mark.parametrize("declared", [False, True])
def test_template_public_metadata_never_exposes_request_credentials(
    client, db_session, admin_headers, declared
):
    content = {
        "input": {"type": "Ip"},
        "output": {"type": "Ip"},
        "request": {
            "url": "https://private.example/?token=private-token",
            "headers": {"Authorization": "private-credential"},
        },
    }
    metadata = {
        "description": "Looks up public IP information.",
        "providers": ["Example"],
        "api_key_requirement": "required",
        "api_key_notes": "Requires EXAMPLE_API_KEY.",
    }
    if declared:
        content["metadata"] = metadata
    template = EnricherTemplate(
        name="metadata-template",
        category="Ip",
        owner_id=db_session.query(Profile).one().id,
        description="Legacy template description",
        content=content,
    )
    db_session.add(template)
    db_session.commit()
    listing = client.get(ADMIN, headers=admin_headers)
    patched = client.patch(
        f"{ADMIN}/template/{template.id}",
        headers=admin_headers,
        json={"is_visible": True},
    )
    for response in (listing, patched):
        assert response.status_code == 200
        assert (
            "private-token" not in response.text
            and "private-credential" not in response.text
        )
        assert "private.example" not in response.text
    row = patched.json()
    if declared:
        assert {key: row[key] for key in metadata} == metadata
    else:
        assert row["api_key_requirement"] == "unknown"
        assert row["providers"] == []
        assert row["description"] == "Legacy template description"


def test_inactive_standalone_admin_cannot_manage_catalog(
    client, db_session, admin_headers
):
    db_session.query(Profile).one().is_active = False
    db_session.commit()
    assert client.get(f"{ADMIN}/access", headers=admin_headers).json() == {
        "can_manage": False
    }
    assert client.get(ADMIN, headers=admin_headers).status_code == 403


def test_authentication_and_explicit_administrator_grant_are_required(
    client, db_session, monkeypatch, builtin
):
    user = Profile(id=uuid4(), email="user@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.email})}"}
    assert client.get(ADMIN).status_code == 401
    assert client.get(f"{ADMIN}/access", headers=headers).json() == {
        "can_manage": False
    }
    assert client.get(ADMIN, headers=headers).status_code == 403
    assert (
        client.patch(
            f"{ADMIN}/builtin/{builtin['name']}",
            headers=headers,
            json={"is_visible": False},
        ).status_code
        == 403
    )
    monkeypatch.setenv("FLOWSINT_ADMIN_USER_IDS", str(user.id))
    assert client.get(f"{ADMIN}/access", headers=headers).json() == {"can_manage": True}


@pytest.mark.parametrize(
    "kind,identifier",
    [("builtin", "missing"), ("template", "bad-uuid"), ("template", str(uuid4()))],
)
def test_unknown_enricher_returns_404(client, admin_headers, kind, identifier):
    response = client.patch(
        f"{ADMIN}/{kind}/{identifier}",
        headers=admin_headers,
        json={"is_visible": False},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body", [{}, {"is_visible": "false"}, {"is_visible": False, "project_id": "other"}]
)
def test_update_payload_is_strict(client, admin_headers, builtin, body):
    assert (
        client.patch(
            f"{ADMIN}/builtin/{builtin['name']}", headers=admin_headers, json=body
        ).status_code
        == 422
    )


def test_global_overrides_apply_to_every_project_but_templates_remain_isolated(
    client, db_session, monkeypatch, builtin
):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")

    async def authenticate(self, session_id, project_id):
        return ProjectScope(
            user_id=session_id,
            project_id=project_id,
            is_platform_admin=session_id == "admin",
        )

    monkeypatch.setattr(AuthClient, "authenticate", authenticate)

    def headers(user="admin", project="a"):
        return {"h-avl-session": user, "h-avl-project": project}

    name = builtin["name"]
    assert (
        client.patch(
            f"{ADMIN}/builtin/{name}", headers=headers(), json={"is_visible": False}
        ).status_code
        == 200
    )
    assert name not in names(client, "/api/enrichers", headers("member"))
    assert name not in names(client, "/api/enrichers", headers("member", "b"))
    listing = client.get(ADMIN, headers=headers(project="b")).json()
    assert next(row for row in listing if row["id"] == name)["is_visible"] is False
    assert (
        client.patch(
            f"{ADMIN}/builtin/{name}",
            headers=headers(project="b"),
            json={"is_visible": True},
        ).status_code
        == 200
    )
    assert name in names(client, "/api/enrichers", headers("member", "a"))
    assert name in names(client, "/api/enrichers", headers("member", "b"))
    assert client.get(ADMIN, headers=headers("member")).status_code == 403
    assert (
        client.patch(
            f"{ADMIN}/builtin/{name}",
            headers=headers("member"),
            json={"is_visible": True},
        ).status_code
        == 403
    )
    with project_scope(ProjectScope(user_id="admin", project_id="a")):
        template = EnricherTemplate(name="a-only", category="Ip", content={})
        db_session.add(template)
        db_session.commit()
        template_id = str(template.id)
    assert not any(
        row["id"] == template_id
        for row in client.get(ADMIN, headers=headers(project="b")).json()
    )
    assert (
        client.patch(
            f"{ADMIN}/template/{template_id}",
            headers=headers(project="b"),
            json={"is_visible": False},
        ).status_code
        == 404
    )
    # Header claims cannot promote an authenticated non-administrator.
    assert (
        client.get(
            ADMIN, headers={**headers("member"), "h-avl-admin": "true"}
        ).status_code
        == 403
    )
