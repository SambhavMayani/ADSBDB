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

BUCKETS = [
    "landing-zone",
    "formatted-zone",
    "trusted-zone",
]

existing_buckets = {
    bucket["Name"] for bucket in minio_client.list_buckets()["Buckets"]
}

for bucket_name in BUCKETS:
    if bucket_name not in existing_buckets:
        minio_client.create_bucket(Bucket=bucket_name)
        print(f"Created bucket: {bucket_name}")
    else:
        print(f"Bucket already exists: {bucket_name}")

print("Storage initialization completed.")
