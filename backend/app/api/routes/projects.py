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
