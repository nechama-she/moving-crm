"""API Gateway WebSocket connect/disconnect handler."""

import os
import time
import json

import boto3
import jwt
from botocore.exceptions import ClientError


def handler(event, context):
    if event.get("action") == "broadcast":
        table = boto3.resource("dynamodb").Table(os.environ["REALTIME_CONNECTIONS_TABLE"])
        client = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ["REALTIME_MANAGEMENT_ENDPOINT"])
        data = json.dumps(event.get("payload") or {}, separators=(",", ":")).encode()
        response = table.scan(ProjectionExpression="connection_id")
        while True:
            for row in response.get("Items", []):
                connection_id = row["connection_id"]
                try:
                    client.post_to_connection(ConnectionId=connection_id, Data=data)
                except client.exceptions.GoneException:
                    table.delete_item(Key={"connection_id": connection_id})
                except ClientError:
                    continue
            if "LastEvaluatedKey" not in response:
                break
            response = table.scan(ProjectionExpression="connection_id", ExclusiveStartKey=response["LastEvaluatedKey"])
        return {"statusCode": 200}
    request = event.get("requestContext", {})
    connection_id = request.get("connectionId", "")
    route = request.get("routeKey", "")
    table = boto3.resource("dynamodb").Table(os.environ["REALTIME_CONNECTIONS_TABLE"])
    if route == "$connect":
        token = (event.get("queryStringParameters") or {}).get("token", "")
        try:
            payload = jwt.decode(
                token,
                os.environ["JWT_SECRET"],
                algorithms=["HS256"],
                issuer=os.getenv("JWT_ISSUER", "moving-crm"),
                options={"require": ["exp", "sub"]},
            )
            if payload.get("role") != "admin":
                return {"statusCode": 403}
        except jwt.PyJWTError:
            return {"statusCode": 401}
        table.put_item(Item={
            "connection_id": connection_id,
            "user_id": payload["sub"],
            "expires_at": int(time.time()) + 86400,
        })
    elif route == "$disconnect":
        table.delete_item(Key={"connection_id": connection_id})
    return {"statusCode": 200}
