# app/models.py
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATA_DIR = (Path(__file__).parent / "data").resolve()
DB_PATH = DATA_DIR / "app.db"

class Base(DeclarativeBase):
    pass

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))      # stored name
    orig_name: Mapped[str] = mapped_column(String(255))     # original upload name
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="video")

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"))
    status: Mapped[str] = mapped_column(String(16), default="queued")      # queued|running|done|failed
    spec_json: Mapped[str] = mapped_column(Text)
    outputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    video: Mapped["Video"] = relationship(back_populates="jobs")

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)

def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
