"""Deployment-only startup: schema and Lambda code must already be installed."""
import json
import os

import boto3


def start(lambda_client, ecs_client, environment):
    function = f"moving-crm-work-queue-stream-{environment}"
    mappings = []
    paginator = lambda_client.get_paginator("list_event_source_mappings")
    for page in paginator.paginate(FunctionName=function):
        mappings.extend(page.get("EventSourceMappings", []))
    expected = {"calls", "sms_messages", "conversations"}
    sources = {row["EventSourceArn"].split(":table/", 1)[-1].split("/", 1)[0] for row in mappings}
    if len(mappings) != 3 or sources != expected:
        raise RuntimeError("Queue startup requires exactly the three configured activity streams")
    for mapping in mappings:
        if mapping["State"] != "Enabled":
            lambda_client.update_event_source_mapping(UUID=mapping["UUID"], Enabled=True)
    # Stream events replay from their checkpoints. Bootstrap can safely overlap.
    ecs_client.update_service(cluster=f"moving-crm-work-queue-{environment}",
        service=f"moving-crm-work-queue-{environment}", desiredCount=1,
        forceNewDeployment=True)
    result = lambda_client.invoke(FunctionName=f"moving-crm-work-queue-worker-{environment}",
                                  InvocationType="Event", Payload=json.dumps({"job": "work_queue"}).encode())
    if result.get("StatusCode") != 202:
        raise RuntimeError("Queue worker startup was not accepted")


if __name__ == "__main__":
    start(boto3.client("lambda"), boto3.client("ecs"), os.getenv("ENVIRONMENT", "dev"))
    print("Queue background processing started; saved results activate automatically after the first complete build.")
