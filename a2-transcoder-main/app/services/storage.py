# app/services/storage.py
from __future__ import annotations
from typing import Tuple, Iterator, Optional
import os
import tempfile

_BACKEND = os.getenv("STORAGE_BACKEND", "local-temp")  # will be "s3" later

def _safe_temp_path(key: str) -> str:
    # Simulate S3-style object keys under the OS temp dir, safely.
    key = key.lstrip("/")

    # Disallow parent dir escapes
    if ".." in key.split("/"):
        raise ValueError("Invalid key")

    base = tempfile.gettempdir()
    path = os.path.normpath(os.path.join(base, key))

    # Ensure we stayed inside the temp directory
    if not path.startswith(os.path.abspath(base) + os.sep):
        raise ValueError("Invalid key path resolution")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    if _BACKEND == "local-temp":
        path = _safe_temp_path(key)
        with open(path, "wb") as f:
            f.write(data)
        return
    raise NotImplementedError("S3 backend not wired yet")

def get_stream(key: str) -> Tuple[Iterator[bytes], str]:
    if _BACKEND == "local-temp":
        path = _safe_temp_path(key)
        if not os.path.exists(path):
            raise FileNotFoundError(key)

        def _iter() -> Iterator[bytes]:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return _iter(), "application/octet-stream"
    raise NotImplementedError("S3 backend not wired yet")

def presign_get(key: str, ttl: int = 300) -> Optional[str]:
    # Local-temp has no presigned URL concept. Return None so callers stream.
    return None
