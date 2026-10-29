from datetime import datetime, timezone
from typing import Literal, cast
from urllib.parse import quote, urlsplit
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from flowsint_core.core.models import Investigation, Sketch
from flowsint_core.core.platform_auth import AccessDenied, SessionRejected
from flowsint_core.core.project_scope import current_scope, revalidate_worker_scope

from .contracts import CardImportCommand, CardImportResult
from .graph import MaterialProjection
from .repository import Avl4ImportOperation, Avl4Material, ImportRepository


class ImportRejected(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


class CardImportService:
    def __init__(
        self, db: Session, graph: MaterialProjection, ui_base_url: str
    ) -> None:
        self.db, self.repo, self.graph = db, ImportRepository(db), graph
        try:
            parsed = urlsplit(ui_base_url)
        except ValueError:
            raise ImportRejected("IMPORT_NOT_CONFIGURED", 503) from None
        if (
            any(char.isspace() or char == "\\" for char in ui_base_url)
            or parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ImportRejected("IMPORT_NOT_CONFIGURED", 503)
        self.ui_base_url = ui_base_url.rstrip("/")

    def _target(self, command: CardImportCommand) -> None:
        scope = current_scope()
        if (
            not scope
            or scope.project_id != command.project_id
            or scope.user_id != command.actor_id
        ):
            raise ImportRejected("IMPORT_FORBIDDEN", 403)
        # Hold the graph/investigation SQL rows through reservation/projection.
        inv = (
            self.db.query(Investigation)
            .filter_by(id=command.investigation_id)
            .with_for_update()
            .first()
        )
        sketch = (
            self.db.query(Sketch)
            .filter_by(id=command.sketch_id, investigation_id=command.investigation_id)
            .with_for_update()
            .first()
        )
        if not inv or not sketch:
            raise ImportRejected("TARGET_NOT_FOUND", 404)

    def _reserve(self, command: CardImportCommand) -> Avl4ImportOperation:
        self._target(command)
        operation = self.repo.operation(command.operation_id)
        if operation:
            if operation.fingerprint != command.fingerprint:
                raise ImportRejected("OPERATION_CONFLICT", 409)
            return operation
        material_id = uuid5(NAMESPACE_URL, "avl4-material:" + command.material_key)
        material = self.repo.material(material_id)
        action = "existing"
        if material is None:
            if command.refresh:
                raise ImportRejected("MATERIAL_NOT_FOUND", 404)
            material = Avl4Material(
                id=material_id,
                material_key=command.material_key,
                investigation_id=command.investigation_id,
                sketch_id=command.sketch_id,
                snapshot=command.snapshot.model_dump(mode="json"),
                snapshot_hash=command.snapshot.content_hash,
                revision=1,
            )
            self.repo.add(material)
            self.db.flush()
            action = "created"
        elif command.refresh:
            if command.expected_snapshot_hash != material.snapshot_hash:
                raise ImportRejected("SNAPSHOT_CONFLICT", 409)
            material.snapshot = command.snapshot.model_dump(mode="json")
            material.snapshot_hash = command.snapshot.content_hash
            material.revision += 1
            action = "updated"
        operation = Avl4ImportOperation(
            operation_id=command.operation_id,
            material_id=material.id,
            fingerprint=command.fingerprint,
            snapshot=material.snapshot,
            snapshot_hash=material.snapshot_hash,
            action=action,
        )
        self.repo.add(operation)
        # Durable first snapshot/intent survives any subsequent graph/commit failure.
        self.repo.commit()
        return operation

    def run(self, command: CardImportCommand) -> CardImportResult:
        try:
            for attempt in range(2):
                try:
                    self._reserve(command)
                    break
                except IntegrityError:
                    self.db.rollback()
                    if attempt:
                        raise ImportRejected("IMPORT_BUSY", 409) from None
            self._target(command)
            operation = self.repo.operation(command.operation_id)
            assert operation is not None
            if operation.result is not None:
                return CardImportResult.model_validate(operation.result)
            material = self.repo.material(operation.material_id)
            assert material is not None
            revalidate_worker_scope()
            # Project the latest SQL snapshot, never an older retried operation.
            node_id = self.graph.project(material)
            material.node_id = node_id
            result = CardImportResult(
                operation_id=operation.operation_id,
                material_id=material.id,
                project_id=command.project_id,
                investigation_id=command.investigation_id,
                sketch_id=command.sketch_id,
                node_id=node_id,
                snapshot_hash=operation.snapshot_hash,
                action=cast(
                    Literal["created", "existing", "updated"], operation.action
                ),
                url=f"{self.ui_base_url}/dashboard/investigations/{command.investigation_id}/graph/{command.sketch_id}#pid={quote(command.project_id, safe='')}",
            )
            operation.result = result.model_dump(mode="json")
            operation.completed_at = datetime.now(timezone.utc)
            self.repo.commit()
            return result
        except (ImportRejected, AccessDenied, SessionRejected, PermissionError):
            self.db.rollback()
            raise
        except Exception:
            self.db.rollback()
            raise ImportRejected("IMPORT_UNAVAILABLE", 503) from None
