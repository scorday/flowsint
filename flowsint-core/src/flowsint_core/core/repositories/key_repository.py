"""Repository for Key model."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import exists

from ..models import Key
from ..project_scope import ActorID, owner_filter
from .base import BaseRepository


class KeyRepository(BaseRepository[Key]):
    model = Key

    def get_by_owner(self, owner_id: ActorID) -> List[Key]:
        return self._db.query(Key).filter(owner_filter(Key, owner_id)).all()

    def get_by_name_and_owner(self, owner_id: ActorID, name: str) -> Key | None:
        return (
            self._db.query(Key)
            .filter(owner_filter(Key, owner_id))
            .filter(Key.name == name)
            .first()
        )

    def get_by_id_and_owner(self, key_id: UUID, owner_id: ActorID) -> Optional[Key]:
        return (
            self._db.query(Key)
            .filter(Key.id == key_id, owner_filter(Key, owner_id))
            .first()
        )

    def chat_key_exist(
        self, owner_id: ActorID, key_name: str = "MISTRAL_API_KEY"
    ) -> bool:
        return self._db.query(
            exists().where(owner_filter(Key, owner_id), Key.name == key_name)
        ).scalar()
