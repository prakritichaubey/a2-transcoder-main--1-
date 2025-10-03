'''
import boto3
import json
from botocore.exceptions import ClientError
import os

REGION_NAME = "ap-southeast-2"
SECRET_NAME = "Video-transcoder"  # replace with your actual name
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "dummy-access-key")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy-secret-key")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")


def get_secrets():
    """Fetch secrets from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name=REGION_NAME)

    try:
        response = client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as e:
        raise RuntimeError(f"Could not fetch secret {SECRET_NAME}: {e}")

    secret_str = response.get("SecretString")
    return json.loads(secret_str)

import os
import boto3
from botocore.exceptions import ClientError
import json

SECRET_NAME = "Video-transcoder"
REGION_NAME = "ap-southeast-2"
#SECRET_NAME = "Video-transcoder"  # replace with your actual name
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "dummy-access-key")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy-secret-key")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")


def get_secrets():
    # If no AWS creds, return dummy/local secrets
    if os.getenv("AWS_ACCESS_KEY_ID") in (None, "", "None"):
        return {
            "JWT_SECRET": os.getenv("JWT_SECRET", "local-secret"),
            "S3_ENDPOINT": "http://minio:9000",
            "AWS_ACCESS_KEY_ID": "minioadmin",
            "AWS_SECRET_ACCESS_KEY": "minioadmin",
        }

    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION"))
    try:
        response = client.get_secret_value(SecretId=SECRET_NAME)
        return json.loads(response["SecretString"])
    except ClientError as e:
        raise RuntimeError(f"Could not fetch secret {SECRET_NAME}: {e}")

'''
import os
import boto3
from botocore.exceptions import ClientError
import json

SECRET_NAME = "Video-transcoder"
REGION_NAME = "ap-southeast-2"
#SECRET_NAME = "Video-transcoder"  # replace with your actual name
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "dummy-access-key")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy-secret-key")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

def get_secrets():
    try:
        client = boto3.client("secretsmanager", region_name=REGION_NAME)
        response = client.get_secret_value(SecretId=SECRET_NAME)
        return json.loads(response["SecretString"])
    except Exception as e:
        print(f"[WARNING] Falling back to local secrets because: {e}")
        return {
            "JWT_SECRET": "localdevsecret",
            "S3_ENDPOINT": "http://host.docker.internal:9000",
            "AWS_ACCESS_KEY_ID": "minioadmin",
            "AWS_SECRET_ACCESS_KEY": "minioadmin",
        }
