import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class MemoryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    key: str
    value: str
    created_at: datetime
