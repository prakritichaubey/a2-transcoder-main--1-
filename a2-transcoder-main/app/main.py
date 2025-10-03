# app/main.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import uuid
from typing import Optional
import os

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Body, Header, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from sqlalchemy.orm import Session

from .services.storage import put_bytes, presign_get, get_stream
from .auth import USERS, create_access_token, get_current_user
from .models import init_db, get_session, Video
from .jobs import router as jobs_router
from app.s3_utils import presign_upload, presign_download
from app.dynamodb import new_video, update_status, list_videos, get_video

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

def get_owner(x_user: str | None = Header(None)):
    # Minimal owner identity for now; replace with real auth later
    return x_user or "demo"

@app.post("/videos/upload-url")
def get_upload_url(
    filename: str = Query(..., description="original filename, e.g., movie.mp4"),
    owner: str = Depends(get_owner),
):
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise HTTPException(500, "S3_BUCKET env not set")

    video_id = str(uuid4())
    s3_key = f"{owner}/{video_id}/{filename}"

    _vid = new_video(owner, s3_key, title=filename)

    presigned = presign_upload(bucket, s3_key, expires=3600)
    return {"video_id": _vid, "bucket": bucket, "key": s3_key, "presigned": presigned}

@app.post("/videos/complete")
def mark_uploaded(payload: dict = Body(...), owner: str = Depends(get_owner)):
    """
    Client calls this after a successful presigned POST upload.
    body: { "video_id": "..." }
    """
    video_id = payload.get("video_id")
    if not video_id:
        raise HTTPException(400, "video_id required")
    update_status(owner, video_id, "UPLOADED")
    return {"ok": True}

@app.post("/videos/{video_id}/processing")
def mark_processing(video_id: str, owner: str = Depends(get_owner)):
    update_status(owner, video_id, "PROCESSING")
    return {"ok": True}

@app.post("/videos/{video_id}/done")
def mark_done(video_id: str, payload: dict = Body(None), owner: str = Depends(get_owner)):
    outputs = payload.get("outputs") if payload else None   # e.g., [{"profile":"720p","key":"..."}]
    update_status(owner, video_id, "DONE", outputs=outputs)
    return {"ok": True}

@app.get("/videos")
def my_videos(owner: str = Depends(get_owner)):
    return {"items": list_videos(owner)}

@app.get("/videos/{video_id}/download-url")
def get_download_url(video_id: str, owner: str = Depends(get_owner)):
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise HTTPException(500, "S3_BUCKET env not set")
    item = get_video(owner, video_id)
    if not item:
        raise HTTPException(404, "Video not found")
    url = presign_download(bucket, item["s3_key"], expires=3600)
    return {"url": url}