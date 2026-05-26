import threading
import logging
from celery import shared_task
from .ai_pipeline import process_document

logger = logging.getLogger(__name__)

@shared_task
def process_document_task(document_id):
    """
    Celery task representing async processing of a document page.
    """
    logger.info(f"Running Celery task process_document_task for ID {document_id}")
    process_document(document_id)


def trigger_document_processing(document_id):
    """
    Orchestrates document processing asynchronously.
    Tries Celery first. If Redis/Celery is unavailable or fails,
    starts a daemonized background Python Thread.
    """
    import sys
    # If running django unit tests, run synchronously to prevent SQLite transaction locking
    if any("test" in arg for arg in sys.argv):
        process_document(document_id)
        return

    try:
        # Try queueing with Celery
        process_document_task.delay(document_id)
        logger.info(f"Document {document_id} successfully queued with Celery.")
    except Exception as e:
        logger.warning(
            f"Celery dispatch failed: {str(e)}. "
            f"Falling back to local daemon thread for async execution."
        )
        # Execute in background thread
        thread = threading.Thread(target=process_document, args=(document_id,))
        thread.daemon = True
        thread.start()
        logger.info(f"Local background thread started for document {document_id}.")
