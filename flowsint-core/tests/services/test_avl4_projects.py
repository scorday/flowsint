"""Project-wide collaboration and isolation without local users or ACL rows."""

from uuid import uuid4

import pytest

from flowsint_core.core.models import (
    Chat,
    CustomType,
    EnricherTemplate,
    EnricherVisibility,
    Investigation,
    InvestigationUserRole,
    Key,
    Profile,
    Sketch,
)
from flowsint_core.core.project_scope import ProjectScope, project_scope
from flowsint_core.core.repositories import (
    ChatRepository,
    CustomTypeRepository,
    EnricherTemplateRepository,
    KeyRepository,
)
from flowsint_core.core.services import (
    create_investigation_service,
    create_sketch_service,
)
from flowsint_core.core.services.exceptions import PermissionDeniedError
from flowsint_core.core.vault import Vault


def scope(user="alice", project="project-a"):
    return project_scope(ProjectScope(user_id=user, project_id=project))


def test_project_members_share_investigations_without_profiles_or_roles(db_session):
    with scope():
        service = create_investigation_service(db_session)
        inv = service.create("Case", "Description", "alice")
        inv_id = inv.id
        assert inv.created_by == "alice"
        assert inv.owner_id is None
    with scope("bob"):
        service = create_investigation_service(db_session)
        assert [i.id for i in service.get_accessible_investigations("bob")] == [inv_id]
        service.update(inv_id, "bob", "Edited", "Description", "active")
        assert service.get_by_id(inv_id, "bob").name == "Edited"
    assert db_session.query(Profile).count() == 0
    assert db_session.query(InvestigationUserRole).count() == 0


def test_other_project_cannot_read_or_modify_investigation(db_session):
    with scope():
        inv_id = create_investigation_service(db_session).create("A", "A", "alice").id
    with scope(project="project-b"):
        service = create_investigation_service(db_session)
        assert service.get_accessible_investigations("alice") == []
        with pytest.raises(PermissionDeniedError):
            service.update(inv_id, "alice", "Stolen", "", "active")


def test_empty_sketch_list_is_shared_with_members_but_not_other_projects(db_session):
    with scope():
        inv_id = create_investigation_service(db_session).create("A", "A", "alice").id
    with scope("bob"):
        assert (
            create_investigation_service(db_session).get_sketches(inv_id, "bob") == []
        )
    with scope("bob", "project-b"):
        with pytest.raises(PermissionDeniedError):
            create_investigation_service(db_session).get_sketches(inv_id, "bob")


def test_cross_project_child_and_project_move_are_rejected(db_session):
    with scope():
        inv = create_investigation_service(db_session).create("A", "A", "alice")
        inv_id = inv.id
    with scope(project="project-b"):
        db_session.add(Sketch(title="Wrong", investigation_id=inv_id))
        with pytest.raises(PermissionError):
            db_session.commit()
        db_session.rollback()
    with scope():
        inv = db_session.query(Investigation).filter_by(id=inv_id).one()
        inv.project_id = "project-b"
        with pytest.raises(PermissionError):
            db_session.commit()
        db_session.rollback()


def test_project_resources_and_public_templates_do_not_cross_projects(db_session):
    with scope():
        db_session.add_all(
            [
                CustomType(name="Custom", schema={}),
                EnricherTemplate(
                    name="lookup", category="Domain", content={}, is_public=True
                ),
                Chat(title="Chat"),
            ]
        )
        db_session.commit()
    with scope("bob"):
        assert len(CustomTypeRepository(db_session).get_by_owner("bob")) == 1
        assert (
            len(EnricherTemplateRepository(db_session).get_by_owner_or_public("bob"))
            == 1
        )
        assert len(ChatRepository(db_session).get_by_owner("bob")) == 1
    with scope("bob", "project-b"):
        assert CustomTypeRepository(db_session).get_by_owner("bob") == []
        assert (
            EnricherTemplateRepository(db_session).get_by_owner_or_public("bob") == []
        )
        assert ChatRepository(db_session).get_by_owner("bob") == []


def test_global_catalog_policy_is_readable_across_projects_and_admin_only(db_session):
    with project_scope(
        ProjectScope(user_id="admin", project_id="project-a", is_platform_admin=True)
    ):
        row = EnricherVisibility(enricher_key="builtin:global-test", is_visible=False)
        db_session.add(row)
        db_session.commit()
        identifier = row.id
        assert row.updated_by == "admin"
    with scope("bob", "project-b"):
        row = db_session.query(EnricherVisibility).filter_by(id=identifier).one()
        assert row.is_visible is False
        row.is_visible = True
        with pytest.raises(PermissionError, match="administrator"):
            db_session.commit()
        db_session.rollback()
        with pytest.raises(PermissionError, match="checked ORM"):
            db_session.query(EnricherVisibility).delete()
        db_session.rollback()
    with project_scope(
        ProjectScope(
            user_id="other-admin", project_id="project-c", is_platform_admin=True
        )
    ):
        row = db_session.query(EnricherVisibility).filter_by(id=identifier).one()
        row.is_visible = True
        db_session.commit()
        assert row.updated_by == "other-admin"
    with scope("alice", "project-a"):
        assert db_session.query(EnricherVisibility).one().is_visible is True


def test_project_vault_is_shared_by_members_and_isolated_by_project(db_session):
    with scope():
        key_id = (
            Vault(db_session, "alice").set_secret("MISTRAL_API_KEY", "test-value").id
        )
    with scope("bob"):
        assert Vault(db_session, "bob").get_secret("MISTRAL_API_KEY") == "test-value"
        assert KeyRepository(db_session).chat_key_exist("bob")
    with scope("bob", "project-b"):
        assert Vault(db_session, "bob").get_secret(str(key_id)) is None
        assert not KeyRepository(db_session).chat_key_exist("bob")
        assert db_session.query(Key).all() == []


def test_unscoped_avl4_database_access_fails_closed(db_session, monkeypatch):
    monkeypatch.setenv("FLOWSINT_AUTH_MODE", "avl4")
    with pytest.raises(PermissionError):
        db_session.query(Investigation).all()
    db_session.add(Investigation(id=uuid4(), name="Unscoped"))
    with pytest.raises(PermissionError):
        db_session.commit()
    db_session.rollback()


def test_standalone_mode_cannot_see_or_modify_avl4_rows(db_session):
    with scope():
        inv = create_investigation_service(db_session).create("A", "A", "alice")
    assert db_session.query(Investigation).all() == []
    inv.name = "Wrong mode"
    with pytest.raises(PermissionError):
        db_session.commit()
    db_session.rollback()


def test_sketch_creation_requires_investigation_in_selected_project(db_session):
    with scope():
        inv_id = create_investigation_service(db_session).create("A", "A", "alice").id
    with scope("bob"):
        sketch = create_sketch_service(db_session).create("Graph", "", inv_id, "bob")
        assert sketch.project_id == "project-a"
        assert sketch.created_by == "bob"
    with scope("bob", "project-b"):
        with pytest.raises(PermissionDeniedError):
            create_sketch_service(db_session).create("Graph", "", inv_id, "bob")


def test_batch_logger_restores_each_project_after_request_context_ends(
    db_session, monkeypatch
):
    import flowsint_core.core.logger as logger_module
    from flowsint_core.core.logger import LoggerSingleton
    from flowsint_core.core.models import Log

    monkeypatch.setattr(LoggerSingleton, "_instance", None)
    logger = LoggerSingleton(batch_size=100, auto_start=False)
    monkeypatch.setattr(logger, "_emit_event", lambda *args: None)
    monkeypatch.setattr(logger_module, "get_db", lambda: iter([db_session]))
    for project in ("project-a", "project-b"):
        with scope(project=project):
            inv = create_investigation_service(db_session).create("Case", "", "alice")
            sketch = create_sketch_service(db_session).create(
                "Graph", "", inv.id, "alice"
            )
            logger.info(str(sketch.id), {"message": project})
    logger.flush()
    for project in ("project-a", "project-b"):
        with scope(project=project):
            logs = db_session.query(Log).all()
            assert [log.content["message"] for log in logs] == [project]
            assert logs[0].created_by == "alice"
    logger.shutdown()
