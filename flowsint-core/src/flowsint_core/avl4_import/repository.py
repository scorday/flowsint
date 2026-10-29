"""Project-scoped persistence for durable import intents and projections."""

import uuid

from sqlalchemy.orm import Session

from flowsint_core.core.models import Avl4ImportOperation, Avl4Material


class ImportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def operation(self, operation_id: uuid.UUID) -> Avl4ImportOperation | None:
        return (
            self.db.query(Avl4ImportOperation)
            .filter_by(operation_id=operation_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def material(self, material_id: uuid.UUID) -> Avl4Material | None:
        return (
            self.db.query(Avl4Material)
            .filter_by(id=material_id)
            .populate_existing()
            .with_for_update()
            .first()
        )

    def add(self, row: Avl4Material | Avl4ImportOperation) -> None:
        self.db.add(row)

    def commit(self) -> None:
        self.db.commit()
