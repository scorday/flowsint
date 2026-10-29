"""Complete graph search and atomic application using existing Celery workers."""

from typing import Any
from uuid import UUID

from ..core.celery import celery
from ..core.graph import create_graph_service
from ..core.graph.exploration_results import ExplorationCancelled, ExplorationResults
from ..core.postgre_db import SessionLocal
from ..core.project_scope import ActorID, current_scope
from ..core.services import create_sketch_service
from ..core.services.exploration_service import ExplorationService
from .project import Avl4ProjectTask


class ExplorationTask(Avl4ProjectTask):
    abstract = True

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        # Includes admission errors and hard worker timeouts. Do not expose the
        # exception (it may contain graph or infrastructure details) to clients.
        if result_id := kwargs.get("result_id"):
            result = ExplorationResults(result_id)
            with result.lock():
                if result.redis.hget(result.key("meta"), "status") in {
                    "queued",
                    "running",
                    "applying",
                }:
                    result.state(
                        "failed", error="Search operation failed. Run the search again."
                    )
        super().on_failure(exc, task_id, args, kwargs, einfo)


def _actor(actor: str) -> ActorID:
    return actor if current_scope() else UUID(actor)


@celery.task(
    name="search_investigation", base=ExplorationTask, time_limit=0, soft_time_limit=0
)
def search_investigation(*, result_id: str, sketch_id: str, actor: str) -> None:
    result = ExplorationResults(result_id)
    try:
        with SessionLocal() as db:
            service = ExplorationService(create_sketch_service(db))
            service.result(UUID(sketch_id), _actor(actor), result_id)
            with result.lock():
                if result.summary()["status"] != "queued":
                    return
                result.state("running")
            graph = create_graph_service(sketch_id)
            repo = graph.repository
            for kind, rows in repo.iter_exploration(
                result.summary()["options"], sketch_id
            ):
                result.check_running()
                if kind != "checkpoint":
                    result.append(kind, rows)
                result.touch()
            service.result(UUID(sketch_id), _actor(actor), result_id)
            with result.lock():
                result.check_running()
                result.state("completed")
    except ExplorationCancelled:
        result.clear_rows()
        return
    except Exception:
        with result.lock():
            if result.redis.exists(result.key("meta")):
                result.state(
                    "failed",
                    error="Could not complete the search. The graph may have changed; retry.",
                )
        raise


@celery.task(
    name="apply_exploration", base=ExplorationTask, time_limit=0, soft_time_limit=0
)
def apply_exploration(
    *, result_id: str, sketch_id: str, actor: str, action: str, title: str = ""
) -> None:
    result = ExplorationResults(result_id)
    with SessionLocal() as db:
        sketches = create_sketch_service(db)
        service = ExplorationService(sketches)
        service.result(UUID(sketch_id), _actor(actor), result_id)
        with result.lock():
            if result.summary()["status"] != "applying" or not result.redis.hsetnx(
                result.key("meta"), "apply_claimed", "1"
            ):
                return
        result.prepare_apply()
        source = sketches.get_by_id(UUID(sketch_id), _actor(actor))
        if action == "create":
            sketch = sketches.create(
                title=title,
                description="",
                investigation_id=source.investigation_id,
                owner_id=_actor(actor),
                result_batches=result.apply_batches,
            )
            created_id = str(sketch.id)
        else:
            sketches.get_for_update(UUID(sketch_id), _actor(actor))
            create_graph_service(
                sketch_id, enable_batching=False
            ).attach_result_batches(result.apply_batches)
            created_id = sketch_id
        result.state("applied", created_sketch_id=created_id)
