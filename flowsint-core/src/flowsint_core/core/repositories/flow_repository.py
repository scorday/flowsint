"""Repository for Flow model."""

from typing import List, Optional

from sqlalchemy import or_

from ..models import Flow
from ..project_scope import ActorID, owner_filter
from .base import BaseRepository


class FlowRepository(BaseRepository[Flow]):
    model = Flow

    def get_all_with_optional_category(
        self, category: Optional[str] = None, user_id: Optional[ActorID] = None
    ) -> List[Flow]:
        query = (
            self._db.query(Flow)
            .filter(or_(Flow.owner_id.is_(None), owner_filter(Flow, user_id)))
            .order_by(Flow.last_updated_at.desc())
        )

        if not category or category.lower() == "undefined":
            return query.all()

        flows = query.all()
        return [
            flow
            for flow in flows
            if flow.category
            and any(cat.lower() == category.lower() for cat in flow.category)
        ]
