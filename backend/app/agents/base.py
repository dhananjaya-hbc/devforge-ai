import abc
import logging
import time
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session

from app.core.llm import LLMProvider
from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.events import log_event

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    def __init__(self, db: Session, project_id: uuid.UUID, llm: LLMProvider):
        self.db = db
        self.project_id = project_id
        self.llm = llm

    def execute(self, task: Any | None = None, input_payload: dict | None = None) -> dict:
        """Standard wrapper that handles DB logging, events, and timings."""
        agent_name = self.__class__.__name__
        task_id = task.id if task else None
        
        run_entry = AgentRun(
            project_id=self.project_id,
            task_id=task_id,
            agent_id=agent_name,
            status=AgentRunStatus.RUNNING,
            input_payload=input_payload,
            created_at=datetime.utcnow()
        )
        self.db.add(run_entry)
        self.db.commit()
        self.db.refresh(run_entry)

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="AGENT_STARTED",
            message=f"Agent {agent_name} started running.",
            agent=agent_name
        )

        # Surface provider backoff to the dashboard: a silent multi-minute wait
        # is indistinguishable from a frozen run.
        def _report_wait(message: str) -> None:
            log_event(
                self.db,
                project_id=self.project_id,
                event_type="AGENT_WAITING",
                message=message,
                agent=agent_name,
            )

        self.llm.retry_listener = _report_wait

        try:
            output = self._run(task, input_payload, run_entry.id)
            
            run_entry.status = AgentRunStatus.COMPLETED
            run_entry.output_payload = output
            run_entry.completed_at = datetime.utcnow()
            self.db.commit()

            log_event(
                self.db,
                project_id=self.project_id,
                event_type="AGENT_COMPLETED",
                message=f"Agent {agent_name} completed task successfully.",
                agent=agent_name
            )
            return output
            
        except Exception as e:
            logger.error(f"Agent {agent_name} failed: {e}", exc_info=True)
            
            run_entry.status = AgentRunStatus.FAILED
            run_entry.error = str(e)
            run_entry.completed_at = datetime.utcnow()
            self.db.commit()

            log_event(
                self.db,
                project_id=self.project_id,
                event_type="AGENT_FAILED",
                message=f"Agent {agent_name} failed: {e}",
                agent=agent_name,
                payload={"error": str(e)}
            )
            raise e

        finally:
            self.llm.retry_listener = None

    @abc.abstractmethod
    def _run(self, task: Any | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        """Internal execution routine; implemented by specialized agents."""
        pass
