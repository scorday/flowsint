"""Permission-checked lifecycle of complete investigation searches."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..graph.exploration import ExplorationOptions
from ..graph.exploration_results import ExplorationResults
from ..project_scope import ActorID, current_scope
from .sketch_service import SketchService


class ExplorationService:
    def __init__(self, sketches: SketchService) -> None:
        self.sketches = sketches

    def result(
        self, sketch_id: UUID, actor: ActorID, result_id: str
    ) -> ExplorationResults:
        self.sketches.get_by_id(sketch_id, actor)
        result = ExplorationResults(result_id)
        scope = current_scope()
        result.authorize(
            str(actor), str(sketch_id), scope.project_id if scope else "__standalone__"
        )
        return result

    def start(self, sketch_id: UUID, actor: ActorID, options: dict) -> dict:
        from ...tasks.exploration import search_investigation
        from ...tasks.project import task_context_kwargs

        self.sketches.get_by_id(sketch_id, actor)
        ExplorationOptions(**options)
        result = ExplorationResults("new")
        scope = current_scope()
        result.create(
            owner=str(actor),
            sketch=str(sketch_id),
            project=scope.project_id if scope else "__standalone__",
            options=options,
        )
        try:
            search_investigation.apply_async(
                kwargs={
                    "result_id": result.id,
                    "sketch_id": str(sketch_id),
                    "actor": str(actor),
                    **task_context_kwargs(),
                }
            )
        except Exception:
            result.state("failed", error="Could not queue search. Retry the search.")
            raise
        return result.summary()

    def access(
        self,
        sketch_id: UUID,
        actor: ActorID,
        result_id: str,
        operation: str,
        data: dict[str, Any],
    ) -> dict:
        result = self.result(sketch_id, actor, result_id)
        if operation == "status":
            return result.summary()
        if operation == "page":
            return result.page(data["kind"], data["page"], data["size"])
        if operation == "select":
            return result.select(
                data["kind"], data["checked"], data["ids"], data["revision"]
            )
        if operation == "cancel":
            with result.lock():
                if result.summary()["status"] in {"queued", "running"}:
                    result.state("cancelled")
            return result.summary()
        if operation == "apply":
            from ...tasks.exploration import apply_exploration
            from ...tasks.project import task_context_kwargs

            sketch = self.sketches.get_by_id(sketch_id, actor)
            if data["action"] == "create":
                if not data.get("title", "").strip():
                    raise ValueError("Enter a sketch name")
                self.sketches._check_permission(
                    actor, sketch.investigation_id, ["create"]
                )
            else:
                self.sketches.get_for_update(sketch_id, actor)
            result.freeze(data["revision"])
            try:
                apply_exploration.apply_async(
                    kwargs={
                        "result_id": result_id,
                        "sketch_id": str(sketch_id),
                        "actor": str(actor),
                        "action": data["action"],
                        "title": data.get("title", ""),
                        **task_context_kwargs(),
                    }
                )
            except Exception:
                result.state(
                    "completed", error="Could not queue sketch creation. Retry."
                )
                raise
            return result.summary()
        raise ValueError("Unknown search operation")
