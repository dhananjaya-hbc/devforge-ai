import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CodeReview(Base):
    __tablename__ = "code_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # PASS, FAIL
    severity: Mapped[str] = mapped_column(String(50), nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    issues: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # List of issues found
    recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # List of improvement suggestions
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project")
