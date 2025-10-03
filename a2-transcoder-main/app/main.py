'''
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
from app.s3_utils import bucket_check, download_S3_file,generate_presigned_get,generate_presigned_put, get_s3_client

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
s3_client = get_s3_client()
bucket_name = os.getenv("S3_Bucket","a2-pair2")

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

@app.post("/videos/presign_url")
def get_presigned_urls(filename:str, user=Depends(get_current_user)):
    stored_name = f"{uuid.uuid4().hex}-{filename}"
    key = f"incoming/{stored_name}"
    bucket_check(bucket_name)
    url = s3_client.generate_presigned_put(
        "put_object",
        Params={"Bucket":bucket_name, "Key": key},
        ExpiresIn=3600)
    return{"upload_url":url, "s3_key":key}

@app.get("/videos/{s3_key}/presign_url")
def create_download_presigned_url(s3_key:str, user=Depends(get_current_user)):
    url = generate_presigned_get(
        "get_object",
        Params={"Bucket":bucket_name,
        "Key": s3_key},
        ExpiresIn=3600
        )
    return{"download_url":url}

@app.post("/videos/notify")
def notify_s3_upload(s3_key:str, original_name:str, user=Depends(get_current_user), db: Session = Depends(get_session)):
    s3_client = get_s3_client()
    #bucket_check(bucket_name)
    try:
        head = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
        size = head["ContentLength"]
        #suffix = Path(original_name).suffix or ".mp4"
        #stored_name = f"{uuid.uuid4().hex}{suffix}"
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 Upload Failed: {str(e)}")
    stored_name = Path(s3_key).name
    v = Video(
            owner=user["username"],
            filename=stored_name,
            orig_name=original_name,
            size_bytes=size,
            created_at=datetime.utcnow(),
        )
    db.add(v); db.commit(); db.refresh(v)
    save_video(str(v.id), user["username"], original_name, stored_name, size)
    return{"video_id": v.id}
'''
from __future__ import annotations
import os
import boto3
import requests
import jwt
import uuid

from pathlib import Path
from datetime import datetime
from typing import Optional
from botocore.exceptions import ClientError
from fastapi import Body

# FastAPI imports
from fastapi import APIRouter, FastAPI, UploadFile, File, Depends, HTTPException, Request, Form, Body
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2AuthorizationCodeBearer
from sqlalchemy.orm import Session # Required for SQLAlchemy dependency

# App-specific imports (Ensure these files exist in your app directory)
from app.auth import USERS, create_access_token, get_current_user
from app.models import init_db, get_session, Video
from app.jobs import router as jobs_router, DATA_DIR, INCOMING_DIR
from app.dynamodb import save_video, list_videos as db_list
from app.s3_utils import bucket_check, download_S3_file, generate_presigned_get, generate_presigned_put, get_s3_client

# ----------------------------
# AWS Cognito settings
# ----------------------------
# **IMPORTANT**: Ensure your environment variables are correctly set for these,
# especially COGNITO_APP_CLIENT_SECRET.
COGNITO_DOMAIN = "https://miniprojectprac.auth.ap-southeast-2.amazoncognito.com"
REGION = "ap-southeast-2"

# Use environment variables first, falling back to hardcoded values for local testing
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "ap-southeast-2_hbwp7LsgA")
APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "2r8jvq74v33dudedddvkiprct7")
APP_CLIENT_SECRET = os.getenv("COGNITO_APP_CLIENT_SECRET", "1rtca7r5vbjkqf0j66sm4o9e0dpcblt5fhjvj14pd5af0jqk8hru")
S3_BUCKET_NAME = os.getenv("S3_BUCKET", "a2-pair2")

COGNITO = boto3.client("cognito-idp", region_name=REGION)

# ----------------------------
# FASTAPI APP INSTANCE & LIFECYCLE
# ----------------------------
app = FastAPI(title="CAB432 Video Transcoder")
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR   = BASE_DIR / "data"

# Serve the frontend and transcoded files
app.mount("/static", StaticFiles(directory="./app/static"), name="static")
app.mount("/outputs", StaticFiles(directory="app/data/outputs"), name="outputs")
app.include_router(jobs_router) # Include your jobs router

@app.get("/")
def root():
    return FileResponse("app/static/index.html")

@app.on_event("startup")
def _startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    init_db() # Initialize your SQLAlchemy database

@app.get("/health")
def health():
    return {"ok": True}


# ----------------------------
# AUTHENTICATION FUNCTIONS (Using Cognito OIDC Flow)
# ----------------------------

redirect_uri = "http://localhost:8000/auth/authorize"

# OAuth2 (for token verification in protected routes)
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{COGNITO_DOMAIN}/login?client_id={APP_CLIENT_ID}&response_type=code&scope=email+openid+profile&redirect_uri={redirect_uri}",
    tokenUrl=f"{COGNITO_DOMAIN}/oauth2/token",
)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Validate Cognito ID token. Returns the decoded token payload (user details).
    """
    try:
        # NOTE: Using verify_signature=False is NOT secure for production. 
        # You should implement JWKS fetching for proper signature verification.
        payload = jwt.decode(token, options={"verify_signature": False})
        # The 'cognito:groups' claim can be used for role-based logic if needed.
        # We'll use the 'username' (which is 'cognito:username' or similar) for ownership.
        username = payload.get("username") or payload.get("cognito:username")
        
        # Simple role assignment for existing code compatibility
        user_role = "user" # Default role
        # Assign 'admin' if the user is in an 'admin' group (example)
        if "admin" in payload.get("cognito:groups", []):
            user_role = "admin"
            
        return {"username": username, "role": user_role}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ----------------------------
# AUTH ROUTES
# ----------------------------

@app.post("/auth/signup")
async def signup(payload: dict = Body(...)):
    username = payload.get("username")
    password = payload.get("password")
    email = payload.get("email")

    if not username or not password or not email:
        raise HTTPException(status_code=400, detail="Missing required fields")

    try:
        response = COGNITO.sign_up(
            ClientId=APP_CLIENT_ID,
            Username=username,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
        return {"message": "User created. Please check your email to confirm.", "user_sub": response["UserSub"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@app.get("/auth/authorize")
def authorize(code: str):
    """Cognito callback after login. Exchange code for tokens."""
    token_url = f"{COGNITO_DOMAIN}/oauth2/token"

    data = {
        "grant_type": "authorization_code",
        "client_id": APP_CLIENT_ID,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    # Cognito requires the client secret to be sent in the Basic Auth header, 
    # not in the body, but the requests library can handle this with the `auth` tuple.
    auth_credentials = (APP_CLIENT_ID, APP_CLIENT_SECRET)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(token_url, data=data, auth=auth_credentials, headers=headers)
    
    if response.status_code != 200:
        # Check logs/details from Cognito error response
        error_detail = response.json()
        raise HTTPException(status_code=400, detail=f"Failed to exchange code for tokens: {error_detail}")

    # For the frontend, you'll likely want to store these tokens securely (e.g., cookies/local storage)
    # The current implementation just returns them as JSON.
    return response.json()

@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return user 

# ----------------------------
# VIDEO AND S3 ROUTES
# ----------------------------

s3_client = get_s3_client()

@app.post("/videos/upload")
def upload_video(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    
    bucket_check(S3_BUCKET_NAME)

    original_name = file.filename or "upload.mp4"
    suffix = Path(original_name).suffix or ".mp4"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    key = f"incoming/{stored_name}"

    try:
        s3_client.upload_fileobj(file.file, S3_BUCKET_NAME, key)

        head = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=key)
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
        # Only show videos owned by the authenticated user
        q = q.filter(Video.owner == user["username"])
    else:
        if owner:
            # Admins can filter by a specific owner
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

@app.post("/videos/presign_url")
def get_presigned_urls(filename:str, user=Depends(get_current_user)):
    stored_name = f"{uuid.uuid4().hex}-{filename}"
    key = f"incoming/{stored_name}"
    bucket_check(S3_BUCKET_NAME)
    
    # Use the helper function from s3_utils (assuming it uses s3_client)
    url = generate_presigned_put(
        "put_object",
        Params={"Bucket":S3_BUCKET_NAME, "Key": key},
        ExpiresIn=3600)
    return{"upload_url":url, "s3_key":key}

@app.get("/videos/{s3_key}/presign_url")
def create_download_presigned_url(s3_key:str, user=Depends(get_current_user)):
    
    # Use the helper function from s3_utils (assuming it uses s3_client)
    url = generate_presigned_get(
        "get_object",
        Params={"Bucket":S3_BUCKET_NAME,
        "Key": s3_key},
        ExpiresIn=3600
        )
    return{"download_url":url}

@app.post("/videos/notify")
def notify_s3_upload(s3_key:str, original_name:str, user=Depends(get_current_user), db: Session = Depends(get_session)):
    s3_client = get_s3_client()
    try:
        head = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        size = head["ContentLength"]
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 Head Failed: {str(e)}")
        
    stored_name = Path(s3_key).name
    v = Video(
        owner=user["username"],
        filename=stored_name,
        orig_name=original_name,
        size_bytes=size,
        created_at=datetime.utcnow(),
    )
    db.add(v); db.commit(); db.refresh(v)
    save_video(str(v.id), user["username"], original_name, stored_name, size)
    return{"video_id": v.id}

# ----------------------------
# PROTECTED TEST ROUTE
# ----------------------------
@app.get("/protected")
async def protected_route(user=Depends(get_current_user)):
    return {"message": "Hello!", "user": user}