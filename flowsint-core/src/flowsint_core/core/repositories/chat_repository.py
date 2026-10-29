"""Repository for Chat and ChatMessage models."""

from typing import List, Optional
from uuid import UUID

from ..models import Chat, ChatMessage
from ..project_scope import ActorID, owner_filter
from .base import BaseRepository


class ChatRepository(BaseRepository[Chat]):
    model = Chat

    def get_by_owner(self, owner_id: ActorID) -> List[Chat]:
        return self._db.query(Chat).filter(owner_filter(Chat, owner_id)).all()

    def get_by_investigation_and_owner(
        self, investigation_id: UUID, owner_id: ActorID
    ) -> List[Chat]:
        return (
            self._db.query(Chat)
            .filter(
                Chat.investigation_id == investigation_id,
                owner_filter(Chat, owner_id),
            )
            .order_by(Chat.created_at.asc())
            .all()
        )

    def get_by_id_and_owner(self, chat_id: UUID, owner_id: ActorID) -> Optional[Chat]:
        return (
            self._db.query(Chat)
            .filter(Chat.id == chat_id, owner_filter(Chat, owner_id))
            .first()
        )

    def add_message(self, message: ChatMessage) -> ChatMessage:
        self._db.add(message)
        return message
