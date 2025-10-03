# app/s3_utils.py
import os
from functools import lru_cache
import boto3

@lru_cache(maxsize=1)
def _s3():
    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-southeast-2").replace("_", "-")
    kwargs = {"region_name": region}
    endpoint = os.getenv("S3_ENDPOINT")
    if endpoint:
        kwargs["endpoint_url"] = endpoint  # LocalStack/MinIO only
    return boto3.client("s3", **kwargs)

def presign_upload(bucket: str, key: str, expires: int = 3600):
    """Returns a presigned POST policy so clients can upload directly to S3."""
    conditions = [
        {"bucket": bucket},
        ["eq", "$key", key],  # exact key (tightest/safer)
    ]
    return _s3().generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields=None,
        Conditions=conditions,
        ExpiresIn=expires,
    )

def presign_download(bucket: str, key: str, expires: int = 3600):
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )
