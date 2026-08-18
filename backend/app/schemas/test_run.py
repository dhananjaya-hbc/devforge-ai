import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    total: int
    passed: int
    failed: int
    coverage: float | None
    failures: list | None
    stdout: str | None
    created_at: datetime
