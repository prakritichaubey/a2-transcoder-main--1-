# app/main.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import uuid
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from .dynamodb import save_video, list_videos as db_list

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Body
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from sqlalchemy.orm import Session

from .auth import USERS, create_access_token, get_current_user
from .models import init_db, get_session, Video
from .jobs import router as jobs_router, DATA_DIR, INCOMING_DIR

app = FastAPI(title="CAB432 Video Transcoder")
# Serve the frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Serve transcoded files so the UI can download them
app.mount("/outputs", StaticFiles(directory="app/data/outputs"), name="outputs")

app.include_router(jobs_router)

# who am I?
@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return user  # {"username": "...", "role": "..."}

@app.get("/")
def root():
    return FileResponse("app/static/index.html")

@app.on_event("startup")
def _startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

@app.get("/health")
def health():
    return {"ok": True}

# --- Auth ---
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
s3_client = boto3.client ("s3", region_name="ap-southeast-2")
bucket_name = "A2-pair"

@app.post("/videos/upload")
def upload_video(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # filename can be None in types; provide a safe fallback
    original_name = file.filename or "upload.mp4"
    suffix = Path(original_name).suffix or ".mp4"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    #dest = INCOMING_DIR / stored_name
    key = f"incoming/{stored_name}"

    # Save file to disk
    #with dest.open("wb") as f:
    #    f.write(file.file.read())

    #size = dest.stat().st_size

    try:
        s3_client.upload_fileobj(file.file, bucket_name, key)

        head = s3_client.head_object(Bucket=bucket_name, Key=key)
        size = head["ContentLength"]
        v = Video(
            owner=user["username"],
            filename=stored_name,
            orig_name=original_name,
            size_bytes=size,
            created_at=datetime.utcnow(),
        )
        db.add(v); db.commit(); db.refresh(v)
        save_video(str(v.id), user["username"], original_name, stored_name, size)
        return {
            "video_id": v.id,
            "stored_name": stored_name,
            "size_bytes": size,
            "orig_name": original_name,
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))

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
            "stored_name": v.filename,
            "size_bytes": v.size_bytes,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in items
    ]