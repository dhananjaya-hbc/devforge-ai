import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.task import TaskStatus


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str
    status: TaskStatus
    priority: int
    assigned_agent: str | None
    dependencies: list[uuid.UUID]
    attempts: int
    result: dict | None
    created_at: datetime
    completed_at: datetime | None
