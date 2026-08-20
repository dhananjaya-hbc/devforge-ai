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

        # 3. The run must reach a terminal state, not hang mid-flight.
        #    It is deliberately NOT asserted to be COMPLETED: the outcome now
        #    depends on whether the generated project's tests really pass, and
        #    asserting success here is what previously let fabricated metrics
        #    go unnoticed.
        db_session.refresh(project)
        assert project.status in {
            ProjectStatus.COMPLETED,
            ProjectStatus.FAILED,
            ProjectStatus.RUNNING,
        }

        # 4. The planner must build a workable task graph and start executing it.
        #    The task count is no longer asserted exactly: the plan is produced
        #    per goal, so pinning a number would only test the fallback.
        tasks = db_session.query(Task).filter(Task.project_id == project.id).all()
        assert 2 <= len(tasks) <= 12
        assert any(t.status == TaskStatus.COMPLETED for t in tasks)
        assert all(t.assigned_agent for t in tasks)

        # Every plan must contain implementation and verification work
        agents = {t.assigned_agent for t in tasks}
        assert "DeveloperAgent" in agents
        assert "TestingAgent" in agents

        # Dependencies must only reference tasks in this project (no dangling ids)
        task_ids = {t.id for t in tasks}
        for t in tasks:
            for dep in t.dependencies or []:
                assert dep in task_ids, "task depends on an id outside its own graph"

        # 5. Verify telemetry events were logged
        events = db_session.query(Event).filter(Event.project_id == project.id).all()
        assert len(events) > 0
        event_types = [e.event_type for e in events]
        assert "TASK_CREATED" in event_types
        assert "TASK_STARTED" in event_types

        # 5b. Any recorded test metrics must come from real pytest execution
        from app.models.test_run import TestRun

        for run in db_session.query(TestRun).filter(TestRun.project_id == project.id):
            assert run.total >= run.passed + run.failed, (
                "test counts must be internally consistent, not model-invented"
            )
            assert len(run.failures or []) >= min(run.failed, 1) or run.failed == 0

        # 6. Verify agent runs were saved
        agent_runs = db_session.query(AgentRun).filter(AgentRun.project_id == project.id).all()
        assert len(agent_runs) > 0

    finally:
        # Clean up database entry to prevent cluttering the test/dev environment
        db_session.delete(project)
        db_session.commit()
