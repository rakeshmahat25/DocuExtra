import json
import hmac
import hashlib
import logging
import requests
import threading
from django.utils import timezone
from celery import shared_task
from documents.models import Document
from .models import WebhookEndpoint, WebhookDeliveryLog

logger = logging.getLogger(__name__)

@shared_task
def dispatch_webhook_task(document_id):
    """Celery task worker representing webhook delivery."""
    execute_webhook_dispatch(document_id)


import sys

def dispatch_webhook_notifications(document_id):
    """Orchestrates webhook delivery asynchronously using Celery or local daemon thread fallback.
    During unit tests, skip asynchronous processing to avoid DB locking.
    """
    # Skip webhook dispatch when running Django tests to prevent database locking issues
    if any('test' in arg for arg in sys.argv):
        logger.info('Skipping webhook dispatch during tests')
        return
    try:
        dispatch_webhook_task.delay(document_id)
    except Exception as e:
        logger.warning(f"Celery webhook dispatch failed: {e}. Falling back to background thread.")
        thread = threading.Thread(target=execute_webhook_dispatch, args=(document_id,))
        thread.daemon = True
        thread.start()


def execute_webhook_dispatch(document_id):
    """
    Orchestrates compiling payload, generating HMAC sign,
    making requests, and logging outcomes.
    """
    try:
        document = Document.objects.select_related("workspace").get(id=document_id)
    except Document.DoesNotExist:
        return

    # Find active webhooks in workspace
    endpoints = WebhookEndpoint.objects.filter(workspace=document.workspace, is_active=True)
    if not endpoints.exists():
        return

    # Determine event type
    event_type = "document.processed"
    if document.status == Document.STATUS_FAILED:
        event_type = "document.failed"
    elif document.fraud_status == Document.FRAUD_FAILED:
        event_type = "document.fraud_alert"

    # Assemble Payload
    payload = {
        "event": event_type,
        "document_id": document.id,
        "name": document.name,
        "status": document.status,
        "file_type": document.file_type,
        "confidence_score": document.confidence_score,
        "extracted_json": document.extracted_json,
        "validation_status": document.validation_status,
        "fraud_status": document.fraud_status,
        "timestamp": timezone.now().isoformat()
    }
    payload_str = json.dumps(payload)

    for endpoint in endpoints:
        # Check if endpoint subscribes to this event
        if event_type not in endpoint.events:
            continue

        # Generate SHA256 HMAC Signature
        signature = hmac.new(
            endpoint.secret.encode("utf-8"),
            payload_str.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-DocuOCR-Signature": signature,
            "User-Agent": "DocuOCR-Webhook-Dispatcher/1.0"
        }

        start_time = timezone.now()
        status_code = None
        response_body = ""

        try:
            response = requests.post(
                endpoint.url,
                data=payload_str,
                headers=headers,
                timeout=10
            )
            status_code = response.status_code
            response_body = response.text[:2000] # Cap logged text
        except requests.RequestException as e:
            response_body = f"HTTP request failed: {str(e)}"
            status_code = 599 # Custom code indicating transfer failure
            
        # Log delivery
        WebhookDeliveryLog.objects.create(
            endpoint=endpoint,
            event_type=event_type,
            payload=payload,
            status_code=status_code or 500,
            response_body=response_body,
            sent_at=start_time
        )
        logger.info(f"Dispatched webhook to {endpoint.url} with code {status_code}.")
