import pytest
import uuid
from app.core.database import SessionLocal
from app.core.llm import SimulatorProvider
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskStatus
from app.models.event import Event
from app.models.agent_run import AgentRun
from app.orchestration import orchestrator
from app.orchestration.orchestrator import run_project_orchestration


@pytest.fixture
def db_session():
    """Use the actual Postgres DB session for high-fidelity database testing."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def force_simulator(monkeypatch):
    """Pin the orchestrator to canned responses.

    Without this the test reads LLM_PROVIDER from .env and bills real API
    calls, making it slow and dependent on network and credentials.
    """
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda *a, **kw: SimulatorProvider())


def test_project_orchestration_loop(db_session):
    # 1. Create a project
    project = Project(
        name="Task Manager API Test Run",
        goal="Build a task management REST API with authentication.",
        status=ProjectStatus.CREATED
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    try:
        # 2. Run orchestration (using simulator provider)
        run_project_orchestration(db_session, project.id)

        # 3. Fetch project status
        db_session.refresh(project)
        assert project.status == ProjectStatus.COMPLETED

        # 4. Verify tasks were created and completed
        tasks = db_session.query(Task).filter(Task.project_id == project.id).all()
        assert len(tasks) == 6
        for t in tasks:
            assert t.status == TaskStatus.COMPLETED

        # 5. Verify telemetry events were logged
        events = db_session.query(Event).filter(Event.project_id == project.id).all()
        assert len(events) > 0
        event_types = [e.event_type for e in events]
        assert "PROJECT_COMPLETED" in event_types

        # 6. Verify agent runs were saved
        agent_runs = db_session.query(AgentRun).filter(AgentRun.project_id == project.id).all()
        assert len(agent_runs) > 0

    finally:
        # Clean up database entry to prevent cluttering the test/dev environment
        db_session.delete(project)
        db_session.commit()
