# app/dynamodb.py
import os, time, uuid
from typing import Optional, List, Dict
import boto3
from boto3.dynamodb.conditions import Key, Attr

TABLE = os.getenv("VIDEOS_TABLE", "videos")
PK = os.getenv("VIDEOS_PK", "owner")      # allow overriding if table differs
SK = os.getenv("VIDEOS_SK", "video_id")

def _ddb():
    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-southeast-2").replace("_", "-")
    return boto3.resource("dynamodb", region_name=region)

def table():
    return _ddb().Table(TABLE)

def new_video(owner: str, s3_key: str, title: Optional[str] = None) -> str:
    vid = str(uuid.uuid4())
    now = int(time.time())
    item = {
        PK: owner,
        SK: vid,
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
        Key={PK: owner, SK: video_id},
        UpdateExpression=expr,
        ExpressionAttributeValues=vals,
        ExpressionAttributeNames=names,
    )

def get_video(owner: str, video_id: str) -> Optional[Dict]:
    resp = table().get_item(Key={PK: owner, SK: video_id})
    return resp.get("Item")

def list_videos(owner: str) -> List[Dict]:
    # If the table's PK is 'owner', we can Query efficiently.
    # If the table's PK is something else (e.g., 'video_id'), fall back to a Scan + filter.
    if PK == "owner":
        resp = table().query(
            KeyConditionExpression=Key(PK).eq(owner),
            ScanIndexForward=False,
            Limit=100,
        )
        return resp.get("Items", [])

    # Fallback for mismatched PK: use Scan filtered by the owner attribute.
    # (OK for small datasets; for scale, add a GSI on 'owner' and query that.)
    resp = table().scan(
        FilterExpression=Attr("owner").eq(owner),
        Limit=100
    )
    return resp.get("Items", [])
