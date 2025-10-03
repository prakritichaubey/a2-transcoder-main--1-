'''
# app/auth.py
import os, time, typing as t
import jwt
import time
import requests
import json
from fastapi import HTTPException, Depends
from app import secrets
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Environment variables (set in your deployment)
COGNITO_REGION = os.getenv("COGNITO_REGION", "ap-southeast-2")
USER_POOL_ID = os.getenv("ap-southeast-2_hbwp7LsgA")
APP_CLIENT_ID = os.getenv("2r8jvq74v33dudedddvkiprct7")

JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
secrets = HTTPBearer(auto_error=False)

_jwks = None
_jwks_last_fetched = 0


# def create_access_token(sub: str, role: str) -> str:
#     now = int(time.time())
#     payload = {"sub": sub, "role": role, "iat": now, "exp": now + JWT_EXPIRE_MIN * 60}
#     return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def get_jwks():
    global _jwks, _jwks_last_fetched
    if _jwks is None or time.time() - _jwks_last_fetched > 3600:
        response = requests.get(JWKS_URL)
        response.raise_for_status()
        _jwks = response.json()
        _jwks_last_fetched = time.time()
    return _jwks

def decode_token(token: str) -> dict:
    try:
        jwks = get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header["kid"]
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        payload = jwt.decode(token, public_key, algorithms=["RS256"], audience=APP_CLIENT_ID)
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    data = decode_token(creds.credentials)
    return {"username": data["sub"], "role": data["role"]}


'''

# app/auth.py
import os, time, typing as t
import jwt
import requests
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# --- Config ---
# Local HS256 JWT (dev) — used when Cognito env vars are not set
JWT_SECRET = os.getenv("JWT_SECRET", "localdevsecret")
JWT_ALGO = "HS256"
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))

# Optional: AWS Cognito (prod)
COGNITO_REGION = os.getenv("COGNITO_REGION", "ap-southeast-2")
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")           # e.g. ap-southeast-2_XXXX
APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "")         # e.g. abcdef123456
JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json" if USER_POOL_ID else ""

security = HTTPBearer(auto_error=False)

# In-memory users for dev; replace with DB/Cognito as needed
USERS: dict[str, dict[str, str]] = {
    "admin": {"password": os.getenv("DEV_ADMIN_PASSWORD", "admin123"), "role": "admin"},
}

# --- Local JWT helpers ---
def create_access_token(sub: str, role: str) -> str:
    now = int(time.time())
    payload = {"sub": sub, "role": role, "iat": now, "exp": now + JWT_EXPIRE_MIN * 60}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def decode_local_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- Optional Cognito verification (if configured) ---
_jwks: dict | None = None
_jwks_last_fetched = 0

def get_jwks() -> dict:
    global _jwks, _jwks_last_fetched
    if not JWKS_URL:
        raise RuntimeError("COGNITO not configured")
    if _jwks is None or time.time() - _jwks_last_fetched > 3600:
        resp = requests.get(JWKS_URL, timeout=5)
        resp.raise_for_status()
        _jwks = resp.json()
        _jwks_last_fetched = time.time()
    return _jwks

def decode_cognito_token(token: str) -> dict:
    try:
        jwks = get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token (kid)")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=APP_CLIENT_ID or None,
            options={"verify_aud": bool(APP_CLIENT_ID)},
        )
        return claims
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

def decode_token(token: str) -> dict:
    if USER_POOL_ID:
        return decode_cognito_token(token)
    return decode_local_token(token)

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    data = decode_token(creds.credentials)
    return {"username": data.get("cognito:username") or data.get("sub"), "role": data.get("role", "user")}