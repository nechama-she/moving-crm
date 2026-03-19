import os
import logging
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("moving-crm")

SSM_PREFIX = os.getenv("SSM_PREFIX", "/moving-crm/")


@lru_cache()
def get_config() -> dict:
    """Load config from SSM Parameter Store, falling back to env vars."""
    config = {
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "DYNAMO_TABLE_NAME": os.getenv("DYNAMO_TABLE_NAME", "leads"),
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "http://localhost:5173"),
    }
    try:
        ssm = boto3.client("ssm", region_name=config["AWS_REGION"])
        resp = ssm.get_parameters_by_path(
            Path=SSM_PREFIX, Recursive=True, WithDecryption=True
        )
        for param in resp.get("Parameters", []):
            key = param["Name"].removeprefix(SSM_PREFIX)
            config[key] = param["Value"]
        logger.info("Loaded %d params from SSM %s", len(resp.get("Parameters", [])), SSM_PREFIX)
    except ClientError:
        logger.warning("Could not reach SSM — using env vars / defaults")
    return config
