import uuid
from django.db import models
from core.models import Workspace

def generate_webhook_secret():
    return f"whsec_{uuid.uuid4().hex}"

class WebhookEndpoint(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField(max_length=500, help_text="Target URL for HTTP POST payload")
    secret = models.CharField(
        max_length=100,
        default=generate_webhook_secret,
        help_text="Secret token to verify payload signature"
    )
    events = models.JSONField(
        default=list,
        blank=True,
        help_text="List of subscribed events: document.processed, document.failed, document.fraud_alert"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.workspace.name} - {self.url} (Active: {self.is_active})"


class WebhookDeliveryLog(models.Model):
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="delivery_logs")
    event_type = models.CharField(max_length=50)
    payload = models.JSONField()
    status_code = models.IntegerField()
    response_body = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.endpoint.url} - {self.event_type} ({self.status_code})"
