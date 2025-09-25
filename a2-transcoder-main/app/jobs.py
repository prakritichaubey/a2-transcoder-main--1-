# app/jobs.py
from __future__ import annotations
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Iterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import get_current_user
from .models import Video, Job, get_session
from .ffmpeg_runner import transcode
from .services.storage import get_stream, put_bytes, presign_get


router = APIRouter(prefix="/jobs", tags=["jobs"])
EXECUTOR = ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2))  # scale with CPU

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None

def _stream_to_tempfile(key: str, suffix: str = "") -> str:
    """
    Materialize an object from storage into a secure temporary file.
    Caller must delete the file when done.
    """
    stream, _content_type = get_stream(key)  # Iterator[bytes], str
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in stream:  # type: ignore
                f.write(chunk)
    except Exception:
        # Clean up partially written file
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path

def _collect_outputs_and_upload(out_dir: Path, job_id: int) -> List[Dict[str, Any]]:
    """
    Upload every file in out_dir to storage under outputs/job_<id>/.
    Return a list of dicts describing each rendition with object keys
    and an optional presigned URL if available.
    """
    results: List[Dict[str, Any]] = []
    for p in sorted(out_dir.glob("*")):
        if not p.is_file():
            continue
        key = f"outputs/job_{job_id}/{p.name}"
        with p.open("rb") as f:
            data = f.read()
        # Basic content-type guess (keep simple; codecs set container)
        content_type = "video/mp4" if p.suffix.lower() in {".mp4", ".m4v"} else "application/octet-stream"
        put_bytes(key, data, content_type)

        url = presign_get(key, ttl=300)
        results.append({
            "key": key,        # object key in storage (e.g., S3 key)
            "name": p.name,    # filename
            "size_bytes": p.stat().st_size,
            "url": url,        # may be None on local-temp backend
        })
    return results

def _run_job(job_id: int) -> None:
    """Runs inside threadpool; opens its own DB session."""
    from .models import SessionLocal  # local import to avoid circulars
    db = SessionLocal()
    tmp_in: Optional[str] = None
    tmp_out_dir: Optional[str] = None
    try:
        job: Optional[Job] = db.get(Job, job_id)
        if not job:
            return

        video: Optional[Video] = db.get(Video, job.video_id)
        if not video:
            job.status = "failed"
            job.error = "Video not found"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        # Mark running
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit(); db.refresh(job)

        # Fetch input from storage to a temp file
        # NOTE: video.filename stores an object key (not a local path)
        in_key = video.filename
        suffix = Path(video.orig_name or "").suffix or ".mp4"
        try:
            tmp_in = _stream_to_tempfile(in_key, suffix=suffix)
        except FileNotFoundError:
            job.status = "failed"
            job.error = f"Input object missing: {in_key}"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        # Prepare a temp output directory
        tmp_out_dir = tempfile.mkdtemp(prefix=f"job_{job.id}_")

        # Parse specs (renditions)
        specs: List[Dict[str, Any]] = json.loads(job.spec_json)

        # Optional intensity control (default high)
        try:
            payload = json.loads(job.spec_json)
            intensity = (payload[0].get("intensity") if payload and isinstance(payload, list) else None) or "high"
        except Exception:
            intensity = "high"

        # Do the transcode (paths are temp-only; will be uploaded immediately)
        try:
            outs = transcode(Path(tmp_in), Path(tmp_out_dir), specs, intensity=intensity)
            # outs is expected to be a list of dicts containing at least {"path": "..."} for each rendition
            outs_uploaded = _collect_outputs_and_upload(Path(tmp_out_dir), job.id)

            # Store only storage metadata (object keys and optional URLs)
            job.status = "done"
            job.outputs_json = json.dumps(outs_uploaded)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
        finally:
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        # Cleanup temporaries
        if tmp_in and os.path.exists(tmp_in):
            try:
                os.remove(tmp_in)
            except OSError:
                pass
        if tmp_out_dir and os.path.isdir(tmp_out_dir):
            try:
                shutil.rmtree(tmp_out_dir, ignore_errors=True)
            except OSError:
                pass
        db.close()

@router.post("/transcode")
def create_transcode_job(
    payload: Dict[str, Any],
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    vid_id = payload.get("video_id")
    if vid_id is None:
        raise HTTPException(400, "video_id is required")

    vid: Optional[Video] = db.get(Video, vid_id)
    if not vid:
        raise HTTPException(404, "Video not found")
    if user["role"] != "admin" and vid.owner != user["username"]:
        raise HTTPException(403, "Not allowed to transcode this video")

    # Use provided renditions or sensible defaults
    specs = payload.get("renditions") or [
        {"width": 1920, "height": 1080, "crf": 18, "suffix": "1080p"},
        {"width": 1280, "height": 720,  "crf": 20, "suffix": "720p"},
        {"width": 854,  "height": 480,  "crf": 22, "suffix": "480p"},
    ]
    intensity = payload.get("intensity", "high")

    job = Job(
        owner=user["username"],
        video_id=vid.id,
        status="queued",
        spec_json=json.dumps(specs),
    )
    db.add(job); db.commit(); db.refresh(job)

    EXECUTOR.submit(_run_job, job.id)

    return {"job_id": job.id, "status": job.status, "intensity": intensity}

@router.get("")
def list_jobs(
    status: Optional[str] = None,
    owner: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    if user["role"] != "admin":
        q = q.filter(Job.owner == user["username"])
    else:
        if owner:
            q = q.filter(Job.owner == owner)

    items = q.order_by(Job.id.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": j.id,
            "owner": j.owner,
            "video_id": j.video_id,
            "status": j.status,
            "started_at": _iso(j.started_at),
            "finished_at": _iso(j.finished_at),
        }
        for j in items
    ]

@router.get("/{job_id}")
def get_job(job_id: int, user=Depends(get_current_user), db: Session = Depends(get_session)):
    j: Optional[Job] = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if user["role"] != "admin" and j.owner != user["username"]:
        raise HTTPException(403, "Not allowed")
    return {
        "id": j.id,
        "video_id": j.video_id,
        "status": j.status,
        "spec": json.loads(j.spec_json),
        "outputs": json.loads(j.outputs_json) if j.outputs_json else [],
        "error": j.error,
        "started_at": _iso(j.started_at),
        "finished_at": _iso(j.finished_at),
    }