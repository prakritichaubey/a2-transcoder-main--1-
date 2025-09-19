import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import os

qut_username = "n11462221@qut.edu.au"
region = "ap-southeast-2"
table_name = "A2-pair2"

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

def save_video(video_id: str, owner: str, orig_name:str, stored_name: str, size_bytes: int):
    try:
        response = dynamodb.put_item(
            TableName=table_name,
            Item={
                "qut-username": {"S": qut_username},
                "video_id": {"S": video_id},
                "owner":{"S":owner},
                "orig_name":{"S":orig_name},
                "stored_name":{"S":stored_name},
                "size_bytes":{"N":str(size_bytes)},
                "created_at":{"S":datetime.utcnow().isoformat()},
            },
        )
        return response
    except ClientError as e:
        print(e)
        return None
    
def get_video(video_id: str):
        try:
            response = dynamodb.get_item(
                TableName = table_name,
                Key={
                    "qut-username": {"S": qut_username},
                    "video_id": {"S":video_id},
                },
            )
            return response.get("Item")
        except ClientError as e:
            print(e)
            return None
        
def list_videos(): 
        try:
            response = dynamodb.query(
                TableName = table_name,
                KeyConditionExpression="#pk = :username",
                ExpressionAttributeNames={"#pk": "qut-username"},
                ExpressionAttributeValues={":username": {"S":qut_username}},
            )
            return response.get("Items", [])
        except ClientError as e:
            print(e)
            return []