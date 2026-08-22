"""One-time production migration for newest-message DynamoDB queries."""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("message-index-migration")

INDEX_NAME = "record-type-timestamp-index"
MARKER_NAME = "/moving-crm/prod/MESSAGE_INDEX_MIGRATION_V1_COMPLETE"
TABLES = {
    "sms_messages": ("phone_number", "timestamp"),
    "conversations": ("user_id", "timestamp"),
}
AWS_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 12})


def _index_is_active_and_correct(client, table_name: str) -> bool:
    description = client.describe_table(TableName=table_name)["Table"]
    index = next(
        (item for item in description.get("GlobalSecondaryIndexes", []) if item["IndexName"] == INDEX_NAME),
        None,
    )
    if not index:
        return False
    expected = [
        {"AttributeName": "record_type", "KeyType": "HASH"},
        {"AttributeName": "timestamp", "KeyType": "RANGE"},
    ]
    if index.get("KeySchema") != expected:
        raise RuntimeError(f"{INDEX_NAME} on {table_name} has the wrong key schema")
    return index.get("IndexStatus") == "ACTIVE"


def _backfill_table(client, table_name: str, partition_key: str, sort_key: str) -> int:
    updated = 0
    start_key = None
    with ThreadPoolExecutor(max_workers=12) as executor:
        while True:
            kwargs = {
                "TableName": table_name,
                "ProjectionExpression": f"{partition_key}, #ts, record_type",
                "ExpressionAttributeNames": {"#ts": sort_key},
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = client.scan(**kwargs)
            missing = [item for item in response.get("Items", []) if "record_type" not in item]

            def update(item):
                try:
                    client.update_item(
                        TableName=table_name,
                        Key={partition_key: item[partition_key], sort_key: item[sort_key]},
                        UpdateExpression="SET record_type = :message",
                        ConditionExpression="attribute_not_exists(record_type)",
                        ExpressionAttributeValues={":message": {"S": "message"}},
                    )
                    return 1
                except ClientError as exc:
                    if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                        return 0
                    raise

            updated += sum(executor.map(update, missing))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
    logger.info("Backfilled %s records in %s", updated, table_name)
    return updated


def _ensure_index(client, table_name: str) -> None:
    description = client.describe_table(TableName=table_name)["Table"]
    indexes = {index["IndexName"]: index for index in description.get("GlobalSecondaryIndexes", [])}
    if INDEX_NAME in indexes:
        _index_is_active_and_correct(client, table_name)
    else:
        create = {
            "IndexName": INDEX_NAME,
            "KeySchema": [
                {"AttributeName": "record_type", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
        billing_mode = description.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
        if billing_mode != "PAY_PER_REQUEST":
            create["ProvisionedThroughput"] = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
        client.update_table(
            TableName=table_name,
            AttributeDefinitions=[
                {"AttributeName": "record_type", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexUpdates=[{"Create": create}],
        )
        logger.info("Started %s creation on %s", INDEX_NAME, table_name)


def _wait_for_indexes(client) -> None:
    deadline = time.monotonic() + 45 * 60
    pending = set(TABLES)
    while pending:
        for table_name in list(pending):
            if _index_is_active_and_correct(client, table_name):
                pending.remove(table_name)
                logger.info("%s is ACTIVE on %s", INDEX_NAME, table_name)
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for indexes on: {', '.join(sorted(pending))}")
        time.sleep(10)


def _verify_index_queries(client) -> None:
    """Do not deploy the API until both indexes accept the query it will use."""
    for table_name in TABLES:
        client.query(
            TableName=table_name,
            IndexName=INDEX_NAME,
            KeyConditionExpression="record_type = :message",
            ExpressionAttributeValues={":message": {"S": "message"}},
            ScanIndexForward=False,
            Limit=1,
        )
        logger.info("Verified newest-message query on %s", table_name)


def migrate() -> None:
    if os.getenv("ENVIRONMENT", "dev").lower() != "prod":
        logger.info("Skipping message index migration outside production")
        return

    ssm = boto3.client("ssm", config=AWS_CONFIG)
    dynamodb = boto3.client("dynamodb", config=AWS_CONFIG)
    try:
        ssm.get_parameter(Name=MARKER_NAME)
        if all(_index_is_active_and_correct(dynamodb, table_name) for table_name in TABLES):
            logger.info("Message index migration already completed; skipping")
            return
        logger.warning("Completion marker exists but indexes are not ready; repairing")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ParameterNotFound":
            raise

    for table_name, keys in TABLES.items():
        _backfill_table(dynamodb, table_name, *keys)
    for table_name in TABLES:
        _ensure_index(dynamodb, table_name)
    _wait_for_indexes(dynamodb)
    _verify_index_queries(dynamodb)
    ssm.put_parameter(Name=MARKER_NAME, Value="complete", Type="String", Overwrite=True)
    logger.info("Production message index migration completed")


if __name__ == "__main__":
    migrate()
