# app/models.py
from __future__ import annotations
from datetime import datetime
import os

from sqlalchemy import create_engine, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/app.db")
ECHO = os.getenv("SQL_ECHO", "0") in {"1", "true", "True"}

class Base(DeclarativeBase):
    pass

engine = create_engine(DATABASE_URL, echo=ECHO, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# --- Models ---
class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    # NOTE: 'filename' now stores a cloud object key (e.g., S3 key), NOT a local filesystem path.
    filename: Mapped[str] = mapped_column(String(512))
    orig_name: Mapped[str] = mapped_column(String(255))  # original client filename
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="video")

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed
    spec_json: Mapped[str] = mapped_column(Text)
    outputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    video: Mapped["Video"] = relationship(back_populates="jobs")

# --- Helpers ---
def init_db():
    # No local directory creation here (stateless). Just ensure tables exist.
    Base.metadata.create_all(engine)

###
def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()