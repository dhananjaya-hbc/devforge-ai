import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.event import Event
from app.models.project import Project
from app.models.task import Task
from app.schemas.event import EventRead
from app.schemas.project import ProjectCreate, ProjectRead
from app.schemas.task import TaskRead
from app.services.events import log_event

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_project_or_404(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    name = payload.name or payload.goal[:80]
    project = Project(name=name, goal=payload.goal)
    db.add(project)
    db.commit()
    db.refresh(project)

    log_event(
        db,
        project_id=project.id,
        event_type="PROJECT_CREATED",
        message=f"Project '{project.name}' created from user goal.",
    )
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    return _get_project_or_404(db, project_id)


@router.get("/{project_id}/tasks", response_model=list[TaskRead])
def list_project_tasks(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Task]:
    _get_project_or_404(db, project_id)
    return db.query(Task).filter(Task.project_id == project_id).order_by(Task.created_at).all()


@router.get("/{project_id}/events", response_model=list[EventRead])
def list_project_events(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Event]:
    _get_project_or_404(db, project_id)
    return db.query(Event).filter(Event.project_id == project_id).order_by(Event.created_at).all()


from fastapi import BackgroundTasks
import asyncio
import json
from fastapi.responses import StreamingResponse
from app.models.project import ProjectStatus
from app.models.artifact import Artifact
from app.models.test_run import TestRun
from app.models.code_review import CodeReview
from app.orchestration.orchestrator import run_project_orchestration


@router.post("/{project_id}/start")
def start_project(project_id: uuid.UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    if project.status in [ProjectStatus.RUNNING, ProjectStatus.PLANNING]:
        raise HTTPException(status_code=400, detail="Project is already running.")
    
    project.status = ProjectStatus.RUNNING
    db.commit()

    def run_in_bg():
        from app.core.database import SessionLocal
        bg_db = SessionLocal()
        try:
            run_project_orchestration(bg_db, project_id)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Background execution failed: {e}")
        finally:
            bg_db.close()
            
    background_tasks.add_task(run_in_bg)
    return {"message": "Project orchestration started in background."}


@router.post("/{project_id}/pause")
def pause_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    if project.status != ProjectStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Only running projects can be paused.")
    project.status = ProjectStatus.PAUSED
    db.commit()
    log_event(db, project_id=project_id, event_type="PROJECT_PAUSED", message="Project execution paused.")
    return {"message": "Project paused."}


@router.post("/{project_id}/resume")
def resume_project(project_id: uuid.UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    if project.status != ProjectStatus.PAUSED:
        raise HTTPException(status_code=400, detail="Only paused projects can be resumed.")
    
    project.status = ProjectStatus.RUNNING
    db.commit()
    log_event(db, project_id=project_id, event_type="REPLAN_STARTED", message="Project execution resumed.")

    def run_in_bg():
        from app.core.database import SessionLocal
        bg_db = SessionLocal()
        try:
            run_project_orchestration(bg_db, project_id)
        finally:
            bg_db.close()

    background_tasks.add_task(run_in_bg)
    return {"message": "Project resumed."}


@router.post("/{project_id}/cancel")
def cancel_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    project.status = ProjectStatus.CANCELLED
    db.commit()
    log_event(db, project_id=project_id, event_type="PROJECT_FAILED", message="Project execution cancelled by user.")
    return {"message": "Project cancelled."}


@router.get("/{project_id}/files")
def list_project_files(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    artifacts = db.query(Artifact).filter(Artifact.project_id == project_id).all()
    return [{"id": str(a.id), "name": a.name, "path": a.path, "created_at": a.created_at} for a in artifacts]


@router.get("/{project_id}/files/{file_id}/content")
def get_file_content(project_id: uuid.UUID, file_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    artifact = db.get(Artifact, file_id)
    if not artifact or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": artifact.content, "path": artifact.path}


@router.get("/{project_id}/tests")
def get_project_tests(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    runs = db.query(TestRun).filter(TestRun.project_id == project_id).order_by(TestRun.created_at.desc()).all()
    return [{
        "id": str(r.id),
        "total": r.total,
        "passed": r.passed,
        "failed": r.failed,
        "coverage": r.coverage,
        "failures": r.failures,
        "stdout": r.stdout,
        "created_at": r.created_at
    } for r in runs]


@router.get("/{project_id}/reviews")
def get_project_reviews(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    reviews = db.query(CodeReview).filter(CodeReview.project_id == project_id).order_by(CodeReview.created_at.desc()).all()
    return [{
        "id": str(r.id),
        "status": r.status,
        "severity": r.severity,
        "issues": r.issues,
        "recommendations": r.recommendations,
        "created_at": r.created_at
    } for r in reviews]


@router.get("/{project_id}/events/stream")
def stream_project_events(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)

    async def event_generator():
        sent_event_ids = set()
        
        initial_events = db.query(Event).filter(Event.project_id == project_id).order_by(Event.created_at.asc()).all()
        for e in initial_events:
            sent_event_ids.add(e.id)
            payload = {
                "id": str(e.id),
                "agent": e.agent,
                "event_type": e.event_type,
                "message": e.message,
                "payload": e.payload,
                "created_at": e.created_at.isoformat()
            }
            yield f"data: {json.dumps(payload)}\n\n"

        while True:
            from app.core.database import SessionLocal
            bg_db = SessionLocal()
            try:
                new_events = bg_db.query(Event).filter(
                    Event.project_id == project_id,
                    ~Event.id.in_(list(sent_event_ids)) if sent_event_ids else True
                ).order_by(Event.created_at.asc()).all()

                for e in new_events:
                    sent_event_ids.add(e.id)
                    payload = {
                        "id": str(e.id),
                        "agent": e.agent,
                        "event_type": e.event_type,
                        "message": e.message,
                        "payload": e.payload,
                        "created_at": e.created_at.isoformat()
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    
            except Exception:
                pass
            finally:
                bg_db.close()
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

