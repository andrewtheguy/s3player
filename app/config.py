import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    s3_endpoint: str
    s3_bucket: str
    s3_region: str
    s3_access_key_id: str
    s3_secret_access_key: str
    database_url: str
    site_password: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        s3_endpoint=os.environ["S3_ENDPOINT"],
        s3_bucket=os.environ["S3_BUCKET"],
        s3_region=os.environ["S3_REGION"],
        s3_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        s3_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        database_url=os.environ["DATABASE_URL"],
        site_password=os.environ["SITE_PASSWORD"],
    )
