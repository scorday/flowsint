"""Project-isolated visibility overrides for the enricher catalog."""

from ..models import EnricherVisibility
from .base import BaseRepository


class EnricherVisibilityRepository(BaseRepository[EnricherVisibility]):
    model = EnricherVisibility

    def get_by_key(self, key: str) -> EnricherVisibility | None:
        return self._db.query(self.model).filter(self.model.enricher_key == key).first()

    def overrides(self) -> dict[str, bool]:
        return {row.enricher_key: row.is_visible for row in self.get_all()}
