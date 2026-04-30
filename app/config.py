import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class S3Settings:
    endpoint: str
    bucket: str
    region: str
    access_key_id: str
    secret_access_key: str


@lru_cache
def get_settings() -> S3Settings:
    return S3Settings(
        endpoint=os.environ["S3_ENDPOINT"],
        bucket=os.environ["S3_BUCKET"],
        region=os.environ["S3_REGION"],
        access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
    )
