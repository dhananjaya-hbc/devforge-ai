import uuid

from sqlalchemy.orm import Session

from app.models.event import Event


def log_event(
    db: Session,
    project_id: uuid.UUID,
    event_type: str,
    message: str,
    agent: str | None = None,
    payload: dict | None = None,
) -> Event:
    event = Event(
        project_id=project_id,
        agent=agent,
        event_type=event_type,
        message=message,
        payload=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
