from django.db import models
from django.conf import settings
from core.models import Workspace, Tenant

class AuditLog(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="audit_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )
    action = models.CharField(max_length=100, help_text="e.g. UPLOAD_DOCUMENT, REVIEW_SUBMIT, LOGIN")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        actor = self.user.username if self.user else "System"
        return f"{actor} - {self.action} ({self.created_at})"


class UsageMetric(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="usage_metrics")
    date = models.DateField(auto_now_add=True)
    document_count = models.IntegerField(default=0)
    processing_time_ms = models.IntegerField(default=0, help_text="Total processing latency in ms")
    api_calls = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.tenant.name} - {self.date}"
