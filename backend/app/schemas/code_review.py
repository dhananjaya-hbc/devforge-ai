import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CodeReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    severity: str
    issues: list | None
    recommendations: list | None
    created_at: datetime
