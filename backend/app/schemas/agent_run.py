import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.agent_run import AgentRunStatus


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    agent_id: str
    status: AgentRunStatus
    input_payload: dict | None
    output_payload: dict | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
