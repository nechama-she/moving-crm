import logging

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException

from db import conversations_table

logger = logging.getLogger("moving-crm")

router = APIRouter(prefix="/api", tags=["Conversations"])


@router.get("/conversations/{user_id}")
def get_conversations(user_id: str):
    """Fetch all messages for a user from the conversations table."""
    try:
        items = []
        response = conversations_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=True,
        )
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = conversations_table.query(
                KeyConditionExpression=Key("user_id").eq(user_id),
                ScanIndexForward=True,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return {"messages": items}
    except ClientError as e:
        logger.error("DynamoDB conversations error: %s", e)
        raise HTTPException(status_code=502, detail="Could not fetch conversations")
