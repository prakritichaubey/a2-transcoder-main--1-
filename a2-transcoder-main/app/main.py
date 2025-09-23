# app/main.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import uuid
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from sqlalchemy.orm import Session

from .services.storage import put_bytes, presign_get, get_stream
from .auth import USERS, create_access_token, get_current_user
from .models import init_db, get_session, Video
from .jobs import router as jobs_router

# ---- App ----
app = FastAPI(title="CAB432 Video Transcoder")

# Serve the frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include background-job routes (e.g., submit transcode job, check status)
app.include_router(jobs_router)

# ---- Root / Health ----
@app.get("/")
def root():
    return FileResponse("app/static/index.html")

@app.on_event("startup")
def _startup():
    # No local data dirs are created here (statelessness).
    init_db()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/health/config")
def health_config():
    return {"storage_backend": "cloud (presigned_or_stream)", "stateless": True}

# who am I?
@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return user  # {"username": "...", "role": "..."}

@app.post("/auth/login")
def login(payload: dict = Body(...)):
    username: Optional[str] = payload.get("username")
    password: Optional[str] = payload.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")

    user = USERS.get(username)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(username, user["role"])
    return {"access_token": token, "token_type": "bearer", "role": user["role"]}

# --- Video upload (unstructured data) ---
@app.post("/videos/upload")
def upload_video(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # filename can be None in types; provide a safe fallback
    original_name = file.filename or "upload.mp4"
    suffix = Path(original_name).suffix or ".mp4"
    object_key = f"uploads/{uuid.uuid4().hex}{suffix}"

    # read file bytes (works for non-async route)
    blob = file.file.read()
    content_type = getattr(file, "content_type", None) or "application/octet-stream"

    # Store bytes in the storage backend (e.g., S3). No local disk writes.
    put_bytes(object_key, blob, content_type)
    size = len(blob)

    v = Video(
        owner=user["username"],
        filename=object_key,  # NOTE: this stores an object key (e.g., S3 key), not a local path
        orig_name=original_name,
        size_bytes=size,
        created_at=datetime.utcnow(),
    )
    db.add(v); db.commit(); db.refresh(v)
    return {
    "video_id": v.id,
    "stored_name": object_key, 
    "size_bytes": size,
    "orig_name": original_name,
}

# ---- Video listing ----
@app.get("/videos")
def list_videos(
    owner: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    q = db.query(Video)
    if user["role"] != "admin":
        q = q.filter(Video.owner == user["username"])
    else:
        if owner:
            q = q.filter(Video.owner == owner)

    items = q.order_by(Video.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": v.id,
            "owner": v.owner,
            "orig_name": v.orig_name,
            "stored_name": v.filename, # this is the object key
            "size_bytes": v.size_bytes,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in items
    ]

# ---- Video download (no local files; presign or stream) ----
@app.get("/videos/{video_id}/download")
def download_video(
    video_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    v = db.query(Video).get(video_id)
    if not v:
        raise HTTPException(404, "Not found")
    if user["role"] != "admin" and v.owner != user["username"]:
        raise HTTPException(403, "Forbidden")

    # Prefer pre-signed URL (private bucket)
    url = presign_get(v.filename, ttl=300)  # wired when S3 is ready
    if url:
        return {"url": url}

    # Fallback: stream from storage backend without touching local disk
    stream, content_type = get_stream(v.filename)
    return StreamingResponse(stream, media_type=content_type)

