import os

import boto3
from dotenv import load_dotenv


load_dotenv()

minio_client = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id=os.getenv("MINIO_ROOT_USER"),
    aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD"),
)

response = minio_client.list_buckets()

print("Connection to MinIO successful.")
print("Existing buckets:", [bucket["Name"] for bucket in response["Buckets"]])
