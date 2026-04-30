from datetime import datetime

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.s3_client import get_s3_client

router = APIRouter(prefix="/api/s3", tags=["s3"])


class S3Object(BaseModel):
    key: str
    size: int
    last_modified: datetime


class ListResponse(BaseModel):
    prefixes: list[str]
    objects: list[S3Object]


@router.get("/list")
def list_top() -> ListResponse:
    settings = get_settings()
    client = get_s3_client()
    try:
        response = client.list_objects_v2(Bucket=settings.bucket, Delimiter="/")
    except ClientError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    prefixes = [p["Prefix"] for p in response.get("CommonPrefixes", [])]
    objects = [
        S3Object(
            key=item["Key"],
            size=item["Size"],
            last_modified=item["LastModified"],
        )
        for item in response.get("Contents", [])
    ]
    return ListResponse(prefixes=prefixes, objects=objects)
