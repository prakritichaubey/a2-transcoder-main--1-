# app/auth.py
import os, time, typing as t
import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))

# Simple demo users (hard-coded per assignment rules)
USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "kimia": {"password": "kimia123", "role": "user"},
    "sara":  {"password": "sara123",  "role": "user"},
}

security = HTTPBearer(auto_error=True)

def create_access_token(sub: str, role: str) -> str:
    now = int(time.time())
    payload = {"sub": sub, "role": role, "iat": now, "exp": now + JWT_EXPIRE_MIN * 60}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    data = decode_token(creds.credentials)
    return {"username": data["sub"], "role": data["role"]}
