import os
import json
import boto3

sqs = boto3.client('sqs')

DLQ_URL = os.environ['EVENTS_DLQ_URL']
MAIN_QUEUE_URL = os.environ['EVENTS_QUEUE_URL']


def main(event, context):
    """
    Manually triggered Lambda to requeue DLQ messages.

    Reads messages from DLQ and sends them back to main queue.
    Use with caution - only requeue if confident the issue is resolved.
    """
    batch_size = event.get('batchSize', 10)
    max_messages = event.get('maxMessages', 100)

    requeued_count = 0
    failed_count = 0

    while requeued_count < max_messages:
        # Receive messages from DLQ
        response = sqs.receive_message(
            QueueUrl=DLQ_URL,
            MaxNumberOfMessages=min(batch_size, max_messages - requeued_count),
            WaitTimeSeconds=1,
        )

        messages = response.get('Messages', [])
        if not messages:
            break

        for message in messages:
            try:
                # Validate message has required fields
                body = json.loads(message['Body'])
                if 'tenantId' not in body or 'eventId' not in body:
                    print(f"Invalid message format: {body}")
                    failed_count += 1
                    continue

                # Requeue to main queue
                sqs.send_message(
                    QueueUrl=MAIN_QUEUE_URL,
                    MessageBody=message['Body'],
                )

                # Delete from DLQ
                sqs.delete_message(
                    QueueUrl=DLQ_URL,
                    ReceiptHandle=message['ReceiptHandle'],
                )

                requeued_count += 1
                print(f"✓ Requeued: {body['tenantId']}/{body['eventId']}")

            except Exception as e:
                print(f"Error processing message: {e}")
                failed_count += 1

    return {
        'statusCode': 200,
        'body': json.dumps({
            'requeued': requeued_count,
            'failed': failed_count,
        })
    }
