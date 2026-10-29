from datetime import datetime
from typing import Optional

from pydantic import UUID4, BaseModel

from .base import ORMBase


class KeyCreate(BaseModel):
    key: str
    name: str


class KeyRead(ORMBase):
    id: UUID4
    owner_id: Optional[UUID4] = None
    name: str
    created_at: datetime | str


class KeyExists(BaseModel):
    exists: bool
    key_name: str = "MISTRAL_API_KEY"
