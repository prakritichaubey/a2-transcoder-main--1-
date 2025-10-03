# app/dynamodb.py
import os, time, uuid
from typing import Optional, List, Dict
import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.getenv("VIDEOS_TABLE", "videos")

def _ddb():
    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-southeast-2").replace("_", "-")
    return boto3.resource("dynamodb", region_name=region)

def table():
    return _ddb().Table(TABLE)

# PK design: owner (HASH), video_id (RANGE)
def new_video(owner: str, s3_key: str, title: Optional[str] = None) -> str:
    vid = str(uuid.uuid4())
    now = int(time.time())
    item = {
        "owner": owner,
        "video_id": vid,
        "s3_key": s3_key,
        "title": title or s3_key.split("/")[-1],
        "status": "UPLOADING",
        "outputs": [],
        "created_at": now,
        "updated_at": now,
    }
    table().put_item(Item=item)
    return vid

def update_status(owner: str, video_id: str, status: str, outputs: Optional[List[Dict]] = None):
    expr = "SET #s=:s, updated_at=:u"
    vals = {":s": status, ":u": int(time.time())}
    names = {"#s": "status"}
    if outputs is not None:
        expr += ", outputs=:o"
        vals[":o"] = outputs
    table().update_item(
        Key={"owner": owner, "video_id": video_id},
        UpdateExpression=expr,
        ExpressionAttributeValues=vals,
        ExpressionAttributeNames=names,
    )

def get_video(owner: str, video_id: str) -> Optional[Dict]:
    resp = table().get_item(Key={"owner": owner, "video_id": video_id})
    return resp.get("Item")

def list_videos(owner: str) -> List[Dict]:
    resp = table().query(
        KeyConditionExpression=Key("owner").eq(owner),
        ScanIndexForward=False,
        Limit=100,
    )
    return resp.get("Items", [])
