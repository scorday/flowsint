"""Exercise the actual public Auth DTOs and client adapter without Redis I/O."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from flowsint_core.core.platform_auth import (
    AccessDenied,
    AuthClient,
    SessionRejected,
    check_access,
)

auth = pytest.importorskip(
    "avl4_auth.pydantic", reason="Install requirements-avl4.txt for Auth client tests"
)
DateRange = auth.DateRange
Project = auth.Project
Session = auth.Session
User = auth.User
UserAccessInfo = auth.UserAccessInfo
UserAppInfo = auth.UserAppInfo
UserProjectInfo = auth.UserProjectInfo


def user(**changes):
    now = datetime.now(timezone.utc)
    data = dict(
        id="auth-user",
        username="alice",
        timezone="Europe/Moscow",
        roles=[],
        groups=[],
        is_deleted=False,
        access=UserAccessInfo(
            apps=[UserAppInfo(app="flowsint", is_enabled=True)],
            projects=[
                UserProjectInfo(
                    project_id="project-a",
                    access_dates=DateRange(
                        from_=now - timedelta(days=1),
                        to_=now + timedelta(days=1),
                    ),
                )
            ],
        ),
    )
    data.update(changes)
    return User(**data)


def test_valid_membership_and_project_wide_access():
    check_access(user(), Project(id="project-a", label="A"))


@pytest.mark.parametrize("change", [dict(is_enabled=False), dict(is_deleted=True)])
def test_disabled_user_is_rejected(change):
    with pytest.raises(SessionRejected):
        check_access(user(**change), Project(id="project-a", label="A"))


@pytest.mark.parametrize("change", [dict(is_enabled=False), dict(is_deleted=True)])
def test_disabled_project_is_denied(change):
    with pytest.raises(AccessDenied):
        check_access(user(), Project(id="project-a", label="A", **change))


def test_missing_membership_is_denied_even_for_app_administrator():
    with pytest.raises(AccessDenied):
        check_access(
            user(roles=["global_access_admin"]), Project(id="project-b", label="B")
        )


def test_disabled_app_and_expired_project_are_denied():
    actor = user()
    actor.access.apps[0].is_enabled = False
    with pytest.raises(AccessDenied):
        check_access(actor, Project(id="project-a", label="A"))
    actor = user()
    actor.access.projects[0].access_dates.to_ = datetime.now(timezone.utc) - timedelta(
        days=2
    )
    with pytest.raises(AccessDenied):
        check_access(actor, Project(id="project-a", label="A"))


def test_private_project_requires_session_bound_identity():
    actor = user(roles=["global_access_privateproject"])
    project = Project(id="private-a", label="Private", is_private=True)
    with pytest.raises(AccessDenied):
        check_access(actor, project, private_project_id="private-other")
    check_access(actor, project, private_project_id="private-a")


def test_auth_adapter_reads_current_snapshots_not_cached_session_grants(monkeypatch):
    import avl4_auth_fastapi
    from avl4_auth_fastapi import api

    actor = user()
    snapshot = Session(
        user_id=actor.id, user_roles=[], access=actor.access.model_copy(deep=True)
    )

    async def decode(value):
        return snapshot if value == "valid-session" else None

    async def get_user(value):
        assert value == actor.id
        return actor

    async def get_project(value):
        return Project(id=value, label="A")

    monkeypatch.setattr(avl4_auth_fastapi, "async_decode_session", decode)
    monkeypatch.setattr(api, "aget_user_by_id", get_user)
    monkeypatch.setattr(api, "aget_project_by_id", get_project)
    verified = asyncio.run(AuthClient().authenticate("valid-session", "project-a"))
    assert verified.user_id == "auth-user"
    actor.access.projects.clear()
    assert snapshot.access.find_project("project-a") is not None
    with pytest.raises(AccessDenied):
        asyncio.run(AuthClient().authenticate("valid-session", "project-a"))
    with pytest.raises(SessionRejected):
        asyncio.run(AuthClient().authenticate("invalid-session", "project-a"))
