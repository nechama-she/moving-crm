"""SmartMoving routes — triggers lead-followup Lambda."""

import json
import os

import boto3
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/smartmoving", tags=["smartmoving"])

FOLLOWUP_FUNCTION = os.getenv("LEAD_FOLLOWUP_FUNCTION", "moving-crm-lead-followup-dev")


@router.post("/sync")
async def run_sync(
    days_back: int = Query(1, ge=0, le=30),
    limit: int = Query(0, ge=0, le=500),
):
    """Invoke the lead-followup Lambda and return its result."""
    client = boto3.client("lambda", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = client.invoke(
        FunctionName=FOLLOWUP_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps({"days_back": days_back, "limit": limit}),
    )
    result = json.loads(resp["Payload"].read())
    return json.loads(result.get("body", "{}"))

