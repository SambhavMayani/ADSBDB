"""Programmatic object storage preparation; no work during import."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestration.storage import create_client

def main():
    client = create_client()
    response = client.list_buckets()
    print("Connection to object storage successful; buckets:", len(response["Buckets"]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
