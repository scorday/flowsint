"""Project admission for trusted Celery messages; cookies never enter the broker."""

from typing import Any
from uuid import UUID

from celery import Task

from ..core.platform_auth import verify_actor_sync
from ..core.project_scope import (
    ProjectScope,
    avl4_enabled,
    current_scope,
    project_scope,
)


def task_context_kwargs() -> dict:
    scope = current_scope()
    if scope is None:
        return {}
    return {
        "avl4_context": {
            "user_id": scope.user_id,
            "project_id": scope.project_id,
            "private_project_id": scope.private_project_id,
        }
    }


class Avl4ProjectTask(Task):
    abstract = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        context = kwargs.pop("avl4_context", None)
        if not avl4_enabled():
            if context:
                raise PermissionError("AVL4 messages require an AVL4 worker")
            return super().__call__(*args, **kwargs)
        if not isinstance(context, dict):
            raise PermissionError("Verified project context is required")
        scope = ProjectScope(**context, worker=True)
        verify_actor_sync(scope.user_id, scope.project_id, scope.private_project_id)
        with project_scope(scope):
            sketch_id = kwargs.get("sketch_id") or (args[2] if len(args) > 2 else None)
            if sketch_id:
                from ..core.models import Sketch
                from ..core.postgre_db import SessionLocal

                with SessionLocal() as session:
                    sketch = (
                        session.query(Sketch)
                        .filter(Sketch.id == UUID(str(sketch_id)))
                        .first()
                    )
                    if sketch is None:
                        raise PermissionError("Task sketch does not belong to project")
            return super().__call__(*args, **kwargs)
