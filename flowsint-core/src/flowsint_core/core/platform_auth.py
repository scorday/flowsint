"""AVL4 access policy over the public Auth client (no Auth storage queries)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from avl4_auth.pydantic import Project, User

from .project_scope import ProjectScope


class SessionRejected(Exception):
    pass


class AccessDenied(Exception):
    pass


def check_access(
    user: User | None, project: Project | None, private_project_id: str | None = None
) -> None:
    if not user or not user.is_enabled or user.is_deleted:
        raise SessionRejected
    app = user.access.find_app("flowsint")
    app_allowed = (
        "global_access_admin" in user.roles
        or ("global_access" in user.roles and (not app or not app.is_access_ended))
        or bool(app and app.is_enabled and not app.is_access_ended)
    )
    if not app_allowed:
        raise AccessDenied
    if not project or not project.is_enabled or project.is_deleted:
        raise AccessDenied
    project_allowed = (
        "/Administrator" in user.groups
        or user.access.find_project(project.id) is not None
        or (
            project.is_private
            and project.id == private_project_id
            and "global_access_privateproject" in user.roles
        )
    )
    if not project_allowed:
        raise AccessDenied


class AuthClient:
    async def authenticate(
        self, session_id: str | None, project_id: str
    ) -> ProjectScope:
        from avl4_auth_fastapi import async_decode_session
        from avl4_auth_fastapi.api import aget_project_by_id, aget_user_by_id

        session = await async_decode_session(session_id)
        if not session:
            raise SessionRejected
        user = await aget_user_by_id(session.user_id)
        project = await aget_project_by_id(project_id)
        check_access(user, project, session.private_project_id)
        if user.id != session.user_id or project.id != project_id:
            raise AccessDenied
        return ProjectScope(
            user_id=user.id,
            project_id=project.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            private_project_id=session.private_project_id,
        )


def verify_actor_sync(
    user_id: str, project_id: str, private_project_id: str | None = None
) -> None:
    from avl4_auth_fastapi.api import get_project_by_id, get_user_by_id

    user = get_user_by_id(user_id)
    project = get_project_by_id(project_id)
    # Background tasks use current project grants; no session cookie enters the queue.
    check_access(user, project, private_project_id)
    if user.id != user_id or project.id != project_id:
        raise AccessDenied
