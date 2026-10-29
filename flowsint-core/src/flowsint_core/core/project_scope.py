"""Verified AVL4 request/task context and SQL project isolation.

The context is installed at the ASGI/task boundary, never from a DTO. Standalone
Flowsint continues to use its existing user/role checks.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, cast
from uuid import UUID

from sqlalchemy import String, event, inspect
from sqlalchemy.orm import (
    InstanceState,
    Mapped,
    ORMExecuteState,
    Session,
    UOWTransaction,
    mapped_column,
    with_loader_criteria,
)
from sqlalchemy.sql.elements import ColumnElement

ActorID = UUID | str


def avl4_enabled() -> bool:
    mode = os.getenv("FLOWSINT_AUTH_MODE", "standalone")
    if mode not in {"standalone", "avl4"}:
        raise RuntimeError("FLOWSINT_AUTH_MODE must be standalone or avl4")
    return mode == "avl4"


@dataclass(frozen=True)
class ProjectScope:
    user_id: str
    project_id: str
    username: str = ""
    first_name: str | None = None
    last_name: str | None = None
    private_project_id: str | None = None
    worker: bool = False
    is_platform_admin: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.user_id, str)
            or not self.user_id
            or not isinstance(self.project_id, str)
            or not self.project_id
            or self.project_id == "__standalone__"
        ):
            raise PermissionError("Verified user and project are required")

    @property
    def id(self) -> str:
        return self.user_id


_scope: ContextVar[ProjectScope | None] = ContextVar("flowsint_project", default=None)


def current_scope() -> ProjectScope | None:
    return _scope.get()


def revalidate_worker_scope() -> None:
    scope = current_scope()
    if scope is None:
        if avl4_enabled():
            raise PermissionError("Verified project context is required")
        return
    if scope.worker:
        from .platform_auth import verify_actor_sync

        verify_actor_sync(scope.user_id, scope.project_id, scope.private_project_id)


@contextmanager
def project_scope(scope: ProjectScope | None) -> Iterator[ProjectScope | None]:
    if scope is not None and (not scope.user_id or not scope.project_id):
        raise PermissionError("Verified user and project are required")
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


class ProjectScoped:
    """Project membership plus an audit actor; no replicated Auth entities."""

    project_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="__standalone__",
        server_default="__standalone__",
        index=True,
    )
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)


def owner_filter(model: Any, owner_id: object) -> ColumnElement[bool]:
    scope = current_scope()
    if scope:
        return cast(ColumnElement[bool], model.project_id == scope.project_id)
    return cast(ColumnElement[bool], model.owner_id == owner_id)


@event.listens_for(Session, "do_orm_execute")
def _filter_project(execute_state: ORMExecuteState) -> None:
    scope = current_scope()
    if not scope:
        if avl4_enabled():
            raise PermissionError("Project scope is required for database access")
        if execute_state.is_orm_statement:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    ProjectScoped,
                    lambda row: row.project_id == "__standalone__",
                    include_aliases=True,
                )
            )
        return
    if not execute_state.is_orm_statement:
        raise PermissionError("Unscoped SQL is forbidden in AVL4 requests")
    if execute_state.is_insert or execute_state.is_update:
        raise PermissionError("AVL4 writes must use checked ORM entities")
    if execute_state.is_delete:
        from .models import EnricherVisibility

        if (
            execute_state.bind_mapper
            and execute_state.bind_mapper.class_ is EnricherVisibility
        ):
            raise PermissionError("Global catalog writes must use checked ORM entities")
    project_id = scope.project_id
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            ProjectScoped,
            lambda row: row.project_id == project_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _check_project_writes(
    session: Session, flush_context: UOWTransaction, instances: Any
) -> None:
    scope = current_scope()
    if not scope:
        if avl4_enabled():
            raise PermissionError("Project scope is required for database writes")
        for row in set(session.new) | set(session.dirty) | set(session.deleted):
            if isinstance(row, ProjectScoped) and row.project_id not in (
                None,
                "__standalone__",
            ):
                raise PermissionError("AVL4 data cannot be changed in standalone mode")
        return
    revalidate_worker_scope()

    from .models import Avl4Material, Chat, EnricherVisibility, Investigation, Sketch

    parents: dict[str, Any] = {
        "investigation_id": Investigation,
        "sketch_id": Sketch,
        "chat_id": Chat,
        "material_id": Avl4Material,
    }
    changed = set(session.new) | set(session.dirty) | set(session.deleted)
    for row in changed:
        if isinstance(row, EnricherVisibility):
            if not scope.is_platform_admin or scope.worker:
                raise PermissionError(
                    "Global catalog settings require an administrator"
                )
            row.updated_by = scope.user_id
            continue
        if not isinstance(row, ProjectScoped):
            raise PermissionError("Legacy identity/ACL writes are disabled in AVL4")
        state = cast(InstanceState[Any], inspect(row))
        if row in session.new:
            if row.project_id not in (None, scope.project_id):
                raise PermissionError("Cannot create an object in another project")
            row.project_id = scope.project_id
            row.created_by = scope.user_id
            # Legacy ownership is unused; Auth identities need no local Profile.
            if hasattr(row, "owner_id"):
                row.owner_id = None
        elif (
            row.project_id != scope.project_id
            or state.attrs.project_id.history.has_changes()
        ):
            raise PermissionError("Cannot move or modify an object across projects")
        if row not in session.deleted:
            for field, model in parents.items():
                parent_id = getattr(row, field, None)
                if parent_id is None:
                    continue
                pending = next(
                    (
                        p
                        for p in session.new
                        if isinstance(p, model) and getattr(p, "id", None) == parent_id
                    ),
                    None,
                )
                parent = (
                    pending
                    or session.query(model).filter(model.id == parent_id).first()
                )
                if parent is None or parent.project_id not in (None, scope.project_id):
                    raise PermissionError(
                        "Parent does not belong to the current project"
                    )
