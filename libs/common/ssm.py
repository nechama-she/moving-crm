"""SSM Parameter Store helpers with simple in-process caching."""

import os

import boto3
from botocore.exceptions import ClientError

_ssm_cache: dict[tuple[str, str], str] = {}


def get_ssm_cached(key: str, region_name: str | None = None) -> str:
    """Get an SSM parameter value (decrypted) with per-process cache."""
    region = region_name or os.getenv("AWS_REGION", "us-east-1")
    cache_key = (region, key)
    if cache_key in _ssm_cache:
        return _ssm_cache[cache_key]

    try:
        ssm = boto3.client("ssm", region_name=region)
        resp = ssm.get_parameter(Name=key, WithDecryption=True)
        val = resp["Parameter"]["Value"]
        _ssm_cache[cache_key] = val
        return val
    except ClientError:
        return ""
