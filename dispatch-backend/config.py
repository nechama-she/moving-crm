import json
import os
from functools import lru_cache
from urllib.parse import quote_plus

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()


def _fetch_secret(arn: str) -> str:
    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
    return sm.get_secret_value(SecretId=arn)["SecretString"]


def _db_password() -> str:
    arn = os.getenv("DB_SECRET_ARN")
    if arn:
        try:
            return json.loads(_fetch_secret(arn)).get("password", "")
        except (ClientError, ValueError):
            pass
    return os.getenv("DB_PASSWORD", "")


def _jwt_secret() -> str:
    arn = os.getenv("JWT_SECRET_ARN")
    if arn:
        try:
            return _fetch_secret(arn)
        except ClientError:
            pass
    return os.getenv("JWT_SECRET", "dev-secret-change-in-prod")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.environ["DB_HOST"]
    port = os.getenv("DB_PORT", "5432")
    name = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    password = _db_password()
    url = f"postgresql://{user}:{quote_plus(password)}@{host}:{port}/{name}"
    if host != "localhost":
        url += "?sslmode=require"
    return url


@lru_cache()
def get_config() -> dict:
    return {
        "DATABASE_URL": _database_url(),
        "JWT_SECRET": _jwt_secret(),
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "http://localhost:5174"),
    }
