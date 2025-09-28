# app/main.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import uuid
from typing import Optional
import boto3
import tempfile
import os
from botocore.exceptions import ClientError


from fastapi import APIRouter,FastAPI, UploadFile, File, Depends, HTTPException, Body
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from sqlalchemy.orm import Session

from app.auth import USERS, create_access_token, get_current_user
from app.models import init_db, get_session, Video
from app.jobs import router as jobs_router, DATA_DIR, INCOMING_DIR
from app.dynamodb import save_video, list_videos as db_list

app = FastAPI(title="CAB432 Video Transcoder")
router = APIRouter()
# Serve the frontend
app.mount("/static", StaticFiles(directory="./app/static"), name="static")

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
s3_client = boto3.client ("s3", 
                          endpoint_url="http://localhost:9000", 
                          aws_access_key_id="minioadmin", 
                          aws_secret_access_key="minioadmin")#region_name="ap-southeast-2")
def download_S3_file(bucket_name: str, object_key: str):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.close()  # Close the file so boto3 can write to it

    s3_client.download_file(bucket_name, object_key)
    return temp_file.name
    
bucket_name = "a2-pair2"

def bucket_check(bucket_name: str):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' exists.")
    except ClientError as e:
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            print(f"Bucket '{bucket_name}' does not exist. Creating bucket...")
            s3_client.create_bucket(Bucket=bucket_name)
            print(f"Bucket '{bucket_name}' created.")
        else:
            print(f"Error checking bucket: {e}")

@app.post("/videos/upload")
def upload_video(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    bucket_check(bucket_name)

    # filename can be None in types; provide a safe fallback
    original_name = file.filename or "upload.mp4"
    suffix = Path(original_name).suffix or ".mp4"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    #dest = INCOMING_DIR / stored_name
    key = f"incoming/{stored_name}"
   # local_file_path = download_S3_file(bucket_name, key)

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
        raise HTTPException(status_code=500, detail=f"S3 Upload Failed: {str(e)}")


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