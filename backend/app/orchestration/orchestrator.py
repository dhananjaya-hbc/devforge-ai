import logging
import uuid
import time
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.llm import get_llm_provider
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskStatus
from app.models.test_run import TestRun
from app.services.events import log_event

# Import all agents
from app.agents.implementations import (
    ProjectManagerAgent,
    RequirementsAgent,
    ArchitectAgent,
    DatabaseAgent,
    DeveloperAgent,
    TestingAgent,
    CodeReviewAgent,
    CriticAgent
)

logger = logging.getLogger(__name__)

AGENT_MAP = {
    "ProjectManagerAgent": ProjectManagerAgent,
    "RequirementsAgent": RequirementsAgent,
    "ArchitectAgent": ArchitectAgent,
    "DatabaseAgent": DatabaseAgent,
    "DeveloperAgent": DeveloperAgent,
    "TestingAgent": TestingAgent,
    "CodeReviewAgent": CodeReviewAgent,
    "CriticAgent": CriticAgent
}


def check_dependencies_completed(db: Session, task: Task) -> bool:
    """Return True if all tasks this task depends on are completed."""
    if not task.dependencies:
        return True
    
    # Fetch status of dependencies
    dep_tasks = db.query(Task).filter(Task.id.in_(task.dependencies)).all()
    for dep in dep_tasks:
        if dep.status != TaskStatus.COMPLETED:
            return False
    return True


def run_project_orchestration(db: Session, project_id: uuid.UUID) -> None:
    """Main execution loop that resolves dependencies, runs agents, and handles recovery."""
    project = db.get(Project, project_id)
    if not project:
        logger.error(f"Project not found: {project_id}")
        return

    log_event(
        db,
        project_id=project_id,
        event_type="REPLAN_STARTED",
        message=f"Starting orchestration execution for project: {project.name}"
    )

    llm = get_llm_provider()

    # Step 1: Initialize Task Graph if no tasks exist
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    if not tasks:
        project.status = ProjectStatus.PLANNING
        db.commit()
        
        pm = ProjectManagerAgent(db, project_id, llm)
        try:
            pm.execute(input_payload={"goal": project.goal})
            # Reload tasks
            tasks = (
            db.query(Task)
            .filter(Task.project_id == project_id)
            .order_by(Task.priority.desc(), Task.created_at)
            .all()
        )
        except Exception as e:
            project.status = ProjectStatus.FAILED
            db.commit()
            logger.error(f"Failed to generate project plan: {e}")
            return

    project.status = ProjectStatus.RUNNING
    db.commit()

    max_loops = 50  # Safeguard against infinite cycles
    loop_count = 0

    while loop_count < max_loops:
        loop_count += 1

        # 0. Honour pause/cancel requested from the API mid-run. Without this
        #    the buttons only changed a badge while the run carried on.
        db.refresh(project)
        if project.status == ProjectStatus.PAUSED:
            log_event(
                db,
                project_id=project_id,
                event_type="PROJECT_PAUSED",
                message="Execution paused. Resume to continue from the current task graph.",
            )
            return
        if project.status == ProjectStatus.CANCELLED:
            log_event(
                db,
                project_id=project_id,
                event_type="PROJECT_FAILED",
                message="Execution cancelled by user.",
            )
            return

        # 1. Reload all tasks from database
        tasks = (
            db.query(Task)
            .filter(Task.project_id == project_id)
            .order_by(Task.priority.desc(), Task.created_at)
            .all()
        )
        
        # 2. Check if all tasks are completed
        all_completed = all(t.status == TaskStatus.COMPLETED for t in tasks)
        if all_completed:
            project.status = ProjectStatus.COMPLETED
            db.commit()
            log_event(
                db,
                project_id=project_id,
                event_type="PROJECT_COMPLETED",
                message="Congratulations! All tasks completed. Project successfully finalized."
            )
            break

        # 3. Check for overall failure (if any task is FAILED and cannot be retried)
        any_failed = any(t.status == TaskStatus.FAILED for t in tasks)
        if any_failed:
            project.status = ProjectStatus.FAILED
            db.commit()
            log_event(
                db,
                project_id=project_id,
                event_type="PROJECT_FAILED",
                message="Project failed. One or more critical tasks failed execution."
            )
            break

        # 4. Find executable tasks (status READY or status PENDING but dependencies are satisfied)
        executable_tasks = []
        for t in tasks:
            if t.status == TaskStatus.READY:
                executable_tasks.append(t)
            elif t.status == TaskStatus.PENDING:
                if check_dependencies_completed(db, t):
                    t.status = TaskStatus.READY
                    db.commit()
                    executable_tasks.append(t)

        # If no tasks are executable but we are not finished, we are blocked
        if not executable_tasks:
            # Check if any are running
            running_tasks = [t for t in tasks if t.status == TaskStatus.RUNNING]
            if not running_tasks:
                project.status = ProjectStatus.FAILED
                db.commit()
                log_event(
                    db,
                    project_id=project_id,
                    event_type="PROJECT_FAILED",
                    message="Orchestrator blocked: Circular dependencies or unresolvable statuses detected."
                )
                break
            else:
                # Waiting is not progress, so it must not consume the loop
                # budget; otherwise ~50s of waiting silently kills a project.
                loop_count -= 1
                time.sleep(1)
                continue

        # 5. Execute next ready task
        target_task = executable_tasks[0]  # Execute sequentially for deterministic MVP flow
        agent_name = target_task.assigned_agent
        
        log_event(
            db,
            project_id=project_id,
            event_type="TASK_STARTED",
            message=f"Starting Task: '{target_task.title}' assigned to {agent_name}."
        )

        target_task.status = TaskStatus.RUNNING
        target_task.attempts += 1
        db.commit()

        # Instantiate target agent
        if agent_name not in AGENT_MAP:
            target_task.status = TaskStatus.FAILED
            db.commit()
            logger.error(f"Agent {agent_name} not found in registry.")
            continue

        agent_class = AGENT_MAP[agent_name]
        agent_instance = agent_class(db, project_id, llm)

        try:
            # Prepare agent context input payload
            input_payload = {"goal": project.goal}
            
            # Execute agent
            output = agent_instance.execute(target_task, input_payload)
            
            # If the task completed was the Testing phase, inspect for failed unit tests
            if agent_name == "TestingAgent":
                # Check the last TestRun failures
                last_test = db.query(TestRun).filter(TestRun.project_id == project_id).order_by(TestRun.created_at.desc()).first()
                if last_test and last_test.failed > 0:
                    # Test failed! Trigger self-recovery debugging loop
                    if target_task.attempts < 3:
                        log_event(
                            db,
                            project_id=project_id,
                            event_type="TEST_FAILED",
                            message=f"Autonomous Debugging Loop triggered (Attempt {target_task.attempts}/3). Resetting Developer task..."
                        )
                        # Reset DeveloperAgent task to PENDING/READY so it fixes the code
                        dev_task = db.query(Task).filter(
                            Task.project_id == project_id, Task.assigned_agent == "DeveloperAgent"
                        ).first()
                        if dev_task:
                            dev_task.status = TaskStatus.READY
                        # Reset testing task to PENDING
                        target_task.status = TaskStatus.PENDING
                        db.commit()
                        continue
                    else:
                        # Max retries exceeded
                        target_task.status = TaskStatus.FAILED
                        db.commit()
                        log_event(
                            db,
                            project_id=project_id,
                            event_type="PROJECT_FAILED",
                            message="Autonomous debugging loop exceeded maximum retries (3/3). Human intervention required."
                        )
                        break

            # Normal success path
            target_task.status = TaskStatus.COMPLETED
            target_task.result = output
            target_task.completed_at = datetime.utcnow()
            db.commit()

            log_event(
                db,
                project_id=project_id,
                event_type="TASK_COMPLETED",
                message=f"Completed Task: '{target_task.title}'."
            )

        except Exception as e:
            # Task failed
            logger.error(f"Task '{target_task.title}' execution failed: {e}")
            if target_task.attempts < 3:
                target_task.status = TaskStatus.READY  # Retry
                log_event(
                    db,
                    project_id=project_id,
                    event_type="REPLAN_STARTED",
                    message=f"Task '{target_task.title}' failed. Retrying (Attempt {target_task.attempts}/3)..."
                )
            else:
                target_task.status = TaskStatus.FAILED
                log_event(
                    db,
                    project_id=project_id,
                    event_type="PROJECT_FAILED",
                    message=f"Task '{target_task.title}' exceeded retry limits and failed."
                )
            db.commit()
