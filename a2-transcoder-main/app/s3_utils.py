import os
import boto3
from botocore.exceptions import ClientError
import tempfile
from app import secrets

def get_s3_client():
    
    return boto3.client("s3", endpoint_url=secrets.get_secrets().get("S3_ENDPOINT"),
                        aws_access_key_id=secrets.AWS_ACCESS_KEY_ID,
                        aws_secret_access_key=secrets.AWS_SECRET_ACCESS_KEY)

def bucket_check(bucket_name: str):
    s3_client = get_s3_client()
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' exists.")
        return
    except ClientError as e:
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            print(f"Bucket '{bucket_name}' does not exist. Creating bucket...")
            s3_client.create_bucket(Bucket=bucket_name)
            print(f"Bucket '{bucket_name}' created.")
        else:
            print(f"Error checking bucket: {e}")
        
        return
    raise

def download_S3_file(bucket_name: str, object_key: str) -> str:
    s3_client = get_s3_client()
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.close()  # Close the file so boto3 can write to it

    s3_client.download_file(bucket_name, object_key)
    return temp_file.name

def generate_presigned_put(bucket_name: str, object_key: str, expiration=3600) -> str:
    s3_client = get_s3_client()
    response = s3_client.generate_presigned_url(
        'put_object',
        Params={'Bucket': bucket_name, 'Key': object_key},
        ExpiresIn=expiration
    )

def generate_presigned_get(bucket_name: str, object_key: str, expiration=3600) -> str:
    s3_client = get_s3_client()
    response = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': object_key},
        ExpiresIn=expiration
    )
    return response