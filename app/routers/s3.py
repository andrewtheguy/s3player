from datetime import datetime

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.s3_client import get_s3_client

router = APIRouter(prefix="/api/s3", tags=["s3"])


class S3File(BaseModel):
    name: str
    size: int
    last_modified: datetime


class ListResponse(BaseModel):
    directories: list[str]
    files: list[S3File]


@router.get("/list")
def list_top() -> ListResponse:
    settings = get_settings()
    client = get_s3_client()
    try:
        response = client.list_objects_v2(Bucket=settings.bucket, Delimiter="/")
    except ClientError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    directories = [p["Prefix"].rstrip("/") for p in response.get("CommonPrefixes", [])]
    files = [
        S3File(
            name=item["Key"],
            size=item["Size"],
            last_modified=item["LastModified"],
        )
        for item in response.get("Contents", [])
    ]
    return ListResponse(directories=directories, files=files)
