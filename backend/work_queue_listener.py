"""Socket-driven PostgreSQL listener. No periodic queries or application polling."""
import asyncio
import json
import os

import boto3
import psycopg2
from botocore.config import Config


def invoke_worker(client):
    response = client.invoke(FunctionName=os.environ["WORK_QUEUE_FUNCTION_NAME"],
        InvocationType="RequestResponse", Payload=b'{"source":"listener"}')
    body = response["Payload"]
    try:
        result = json.loads(body.read())
    finally:
        body.close()
    if response.get("StatusCode") != 200 or response.get("FunctionError"):
        raise RuntimeError("Queue worker failed; restart and recover durable work")
    return result


async def listen():
    secret = json.loads(boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["DB_SECRET_ARN"])["SecretString"])
    connection = psycopg2.connect(
        host=os.environ["DB_HOST"], dbname=os.environ["DB_NAME"],
        user=secret["username"], password=secret["password"], sslmode="require",
        connect_timeout=10, keepalives=1, keepalives_idle=60,
        keepalives_interval=10, keepalives_count=3,
    )
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("LISTEN work_queue_changed")
    loop = asyncio.get_running_loop()
    client = boto3.client("lambda", config=Config(connect_timeout=5, read_timeout=75,
        retries={"mode": "standard", "max_attempts": 3}))
    pending = False
    running = False
    failed = loop.create_future()

    async def dispatch():
        nonlocal pending, running
        try:
            pending = False
            # Keep this dispatch in flight for the ENTIRE worker execution.
            # Any number of arriving notifications become just one pending wake.
            result = await asyncio.to_thread(invoke_worker, client)
            pending = pending or bool(result.get("initializing") or result.get("pending"))
        except Exception as exc:
            if not failed.done():
                failed.set_exception(exc)
        finally:
            running = False
            if pending and not failed.done():
                wake()

    def wake():
        nonlocal pending, running
        pending = True
        if not running:
            running = True
            loop.create_task(dispatch())

    def readable():
        try:
            # Driver consumes bytes ONLY when the OS reports socket readability.
            connection.poll()
            if connection.notifies:
                connection.notifies.clear()
                wake()
        except Exception as exc:
            if not failed.done():
                failed.set_exception(exc)

    loop.add_reader(connection.fileno(), readable)
    wake()  # LISTEN first, then recover durable work missed during disconnection.
    try:
        await failed
    finally:
        loop.remove_reader(connection.fileno())
        connection.close()


if __name__ == "__main__":
    # A broken connection exits the task. ECS replaces it and startup recovers.
    asyncio.run(listen())
