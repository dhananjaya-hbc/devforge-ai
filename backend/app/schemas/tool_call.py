import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    agent_run_id: uuid.UUID | None
    tool_name: str
    input_payload: dict | None
    output_payload: str | None
    status: str
    duration_ms: float | None
    created_at: datetime
