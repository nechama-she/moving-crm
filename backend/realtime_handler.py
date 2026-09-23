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
        response = table.scan()
        while True:
            for row in response.get("Items", []):
                # Customer sockets must never receive staff broadcasts or another move's events.
                target = event.get('payload', {}).get('customer_lead_id')
                report_target = event.get('payload', {}).get('report_lead_id')
                if report_target:
                    if row.get('report_lead_id') != report_target:
                        continue
                elif row.get('report_lead_id'):
                    continue
                if target:
                    if row.get('customer_lead_id') != target:
                        continue
                elif row.get('customer_lead_id'):
                    continue
                if int(row.get('expires_at', 0)) <= int(time.time()):
                    continue
                connection_id = row["connection_id"]
                try:
                    client.post_to_connection(ConnectionId=connection_id, Data=data)
                except client.exceptions.GoneException:
                    table.delete_item(Key={"connection_id": connection_id})
                except ClientError:
                    continue
            if "LastEvaluatedKey" not in response:
                break
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
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
            if payload.get("role") not in ("admin", "customer_updates", "report_updates"):
                return {"statusCode": 403}
            if payload.get('role') == 'report_updates' and (payload.get('purpose') != 'report_updates' or not payload.get('lead_id')):
                return {'statusCode': 403}
            if payload.get('role') == 'customer_updates' and (payload.get('purpose') != 'customer_updates' or not payload.get('lead_id')):
                return {"statusCode": 403}
        except jwt.PyJWTError:
            return {"statusCode": 401}
        item = {
            "connection_id": connection_id,
            "user_id": payload["sub"],
            "expires_at": int(payload['exp']),
        }
        if payload.get('role') == 'customer_updates':
            item['customer_lead_id'] = payload['lead_id']
        if payload.get('role') == 'report_updates':
            item['report_lead_id'] = payload['lead_id']
        table.put_item(Item=item)
    elif route == "$disconnect":
        table.delete_item(Key={"connection_id": connection_id})
    return {"statusCode": 200}
