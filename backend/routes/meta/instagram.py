import logging

from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException

from db import conversations_table

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api/meta/instagram", tags=["Instagram"])


# ---------------------------------------------------------------------------
# GET  /{user_id}  — fetch Instagram messages
# ---------------------------------------------------------------------------

@router.get("/{user_id}")
def get_instagram_messages(user_id: str):
    """Fetch Instagram messages for a user from the conversations table."""
    try:
        items = []
        response = conversations_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            FilterExpression=Attr("platform").eq("instagram"),
            ScanIndexForward=True,
        )
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = conversations_table.query(
                KeyConditionExpression=Key("user_id").eq(user_id),
                FilterExpression=Attr("platform").eq("instagram"),
                ScanIndexForward=True,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return {"messages": items}
    except ClientError as e:
        logger.error("DynamoDB conversations error: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch Instagram messages")
