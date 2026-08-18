import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import ProjectStatus


class ProjectCreate(BaseModel):
    goal: str = Field(min_length=10, description="Natural-language software requirement")
    name: str | None = Field(default=None, description="Optional short name; derived from the goal if omitted")


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    goal: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
