'''
# app/jobs.py
from __future__ import annotations
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.models import Video, Job, get_session
from app.ffmpeg_runner import transcode

DATA_DIR = Path(__file__).parent / "data"
INCOMING_DIR = DATA_DIR / "incoming"
OUTPUTS_DIR = DATA_DIR / "outputs"
INCOMING_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/jobs", tags=["jobs"])
EXECUTOR = ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) # could be adjustted to scale CPU

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None

def _run_job(job_id: int) -> None:
    """Runs inside threadpool; opens its own DB session."""
    from .models import SessionLocal # local import to avoid circulars
    db = SessionLocal()
    try:
        job: Optional[Job] = db.get(Job, job_id)
        if not job:
            return

        video: Optional[Video] = db.get(Video, job.video_id)
        if not video:
            job.status = "failed"
            job.error = "Video not found"
            db.commit()
            return

        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit(); db.refresh(job)

        specs: List[Dict[str, Any]] = json.loads(job.spec_json)
        in_path = INCOMING_DIR / video.filename
        if not in_path.exists():
            job.status = "failed"
            job.error = f"Input file missing: {in_path}"
            db.commit()
            return

        out_dir = OUTPUTS_DIR / f"job_{job.id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            # default to "high" if not present
            intensity = (payload := json.loads(job.spec_json)) and payload[0].get("intensity", "high") if False else "high"
            outs = transcode(in_path, out_dir, specs, intensity = "high") 
            outs = [
                {**o, "url": f"/outputs/job_{job.id}/{Path(o['path']).name}"}
                for o in outs
            ]
            job.status = "done"
            job.outputs_json = json.dumps(outs)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
        finally:
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
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

    specs = payload.get("renditions") or [
        {"width": 1920, "height": 1080, "crf": 18, "suffix": "1080p"},
        {"width": 1280, "height": 720, "crf": 20, "suffix": "720p"},
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

'''
# app/jobs.py
from __future__ import annotations
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.models import Video, Job, get_session
from app.ffmpeg_runner import transcode
from app import secrets
from app.s3_utils import get_s3_client
from app.dynamodb import save_video  # later extend with update_video_status

router = APIRouter(prefix="/jobs", tags=["jobs"])
EXECUTOR = ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2))
DATA_DIR = Path(__file__).parent / "data"
INCOMING_DIR = DATA_DIR / "incoming"
OUTPUTS_DIR = DATA_DIR / "outputs"
INCOMING_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
BUCKET = "a2-pair2"
s3 = get_s3_client()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _run_job(job_id: int) -> None:
    """Worker: download from S3, transcode, upload outputs back to S3."""
    from .models import SessionLocal
    db = SessionLocal()
    try:
        job: Optional[Job] = db.get(Job, job_id)
        if not job:
            return

        video: Optional[Video] = db.get(Video, job.video_id)
        if not video:
            job.status = "failed"
            job.error = "Video not found"
            db.commit()
            return

        #s3 = get_s3_client()

        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit(); db.refresh(job)

        # Parse transcoding specs + intensity
        specs: List[Dict[str, Any]] = json.loads(job.spec_json)
        intensity = "high"
        if specs and isinstance(specs, list):
            intensity = specs[0].get("intensity", "high")

        in_key = f"incoming/{video.filename}"

        with tempfile.TemporaryDirectory() as tmpdir:
            local_in = Path(tmpdir) / video.filename
            try:
                s3.download_file(BUCKET, in_key, str(local_in))
            except Exception as e:
                job.status = "failed"
                job.error = f"S3 download failed: {e}"
                db.commit()
                return

            out_dir = Path(tmpdir) / f"job_{job.id}"
            out_dir.mkdir(parents=True, exist_ok=True)

            try:
                outs = transcode(local_in, out_dir, specs, intensity)

                s3_outs = []
                for o in outs:
                    out_path = Path(o["path"])
                    out_key = f"outputs/job_{job.id}/{out_path.name}"
                    s3.upload_file(str(out_path), BUCKET, out_key)

                    url = s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": BUCKET, "Key": out_key},
                        ExpiresIn=3600,
                    )
                    s3_outs.append({**o, "s3_key": out_key, "url": url})

                job.status = "done"
                job.outputs_json = json.dumps(s3_outs)
            except Exception as e:
                job.status = "failed"
                job.error = str(e)
            finally:
                job.finished_at = datetime.utcnow()
                db.commit()

        # Optionally: update DynamoDB record for this video
        try:
            save_video(
                str(video.id),
                video.owner,
                video.orig_name,
                f"incoming/{video.filename}",
                video.size_bytes,
            )
        except Exception:
            pass  # don’t crash job if DynamoDB update fails

    finally:
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

    specs = payload.get("renditions") or [
        {"width": 1920, "height": 1080, "crf": 18, "suffix": "1080p"},
        {"width": 1280, "height": 720, "crf": 20, "suffix": "720p"},
        {"width": 854, "height": 480, "crf": 22, "suffix": "480p"},
    ]

    job = Job(
        owner=user["username"],
        video_id=vid.id,
        status="queued",
        spec_json=json.dumps(specs),
    )
    db.add(job); db.commit(); db.refresh(job)

    EXECUTOR.submit(_run_job, job.id)

    return {"job_id": job.id, "status": job.status}


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