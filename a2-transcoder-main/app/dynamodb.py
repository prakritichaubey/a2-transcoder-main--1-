import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import os

qut_username = "n11462221@qut.edu.au"
region = os.getenv("AWS_REGION","ap-southeast-2")
table_name = os.getenv("DYNAMODB_TABLE", "a2-pair2-videos")
dynamodb = boto3.client("dynamodb", region_name=region)

def create_table():
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            AttributeDefinitions=[
                 {"AttributeName": "qut-username", "AttributeType": "S"},
                {"AttributeName": "video_id", "AttributeType": "S"},
            ],
            KeySchema=[
                 {"AttributeName": "qut-username", "KeyType": "HASH"},
                {"AttributeName": "video_id", "KeyType": "RANGE"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits":1,"WriteCapacityUnits":1},
        )
        print("Create Table Response:", response)
    except ClientError as e:
        print(e)

def save_video(video_id: str, username: str, orig_name:str, stored_name: str, size_bytes: int):
    dynamodb.put_item(
        TableName=table_name,
        Item={
            "qut-username": {"S": username},
            "video_id": {"S": video_id},
            "orig_name": {"S": orig_name},
            "stored_name": {"S": stored_name},
            "size_bytes": {"N": str(size_bytes)},
            #"status": {"S": status},
            "created_at": {"S": datetime.utcnow().isoformat()},
        }
    )
    
def get_video(video_id: str, username: str):
        try:
            response = dynamodb.get_item(
                TableName = table_name,
                Key={
                    "qut-username": {"S": username},
                    "video_id": {"S":video_id},
                },
            )
            return response.get("Item")
        except ClientError as e:
            print(e)
            return None
        
def list_videos(username: str): 
    resp = dynamodb.query(
        TableName=table_name,
        KeyConditionExpression="#pk = :user",
        ExpressionAttributeNames={"#pk": "qut-username"},
        ExpressionAttributeValues={":user": {"S": username}},
    )
    return resp.get("Items", [])
