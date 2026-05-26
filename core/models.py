import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_REVIEWER = "reviewer"
    ROLE_OPERATOR = "operator"
    ROLE_AUDITOR = "auditor"
    ROLE_CLIENT = "client"

    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_REVIEWER, "Reviewer"),
        (ROLE_OPERATOR, "Operator"),
        (ROLE_AUDITOR, "Auditor"),
        (ROLE_CLIENT, "Client"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    is_mfa_enabled = models.BooleanField(default=False)
    profile_image = models.ImageField(upload_to="profiles/", blank=True, null=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Tenant(models.Model):
    name = models.CharField(max_length=255)
    subdomain = models.CharField(max_length=100, unique=True)
    api_key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    gemini_api_key = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Workspace(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tenant.name} - {self.name}"


class WorkspaceMember(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="workspaces_membership")
    role = models.CharField(max_length=20, choices=User.ROLE_CHOICES, default=User.ROLE_OPERATOR)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "user")

    def __str__(self):
        return f"{self.user.username} in {self.workspace.name} as {self.role}"


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    max_documents_per_month = models.IntegerField(default=100)
    features = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.name} - ${self.price}/mo"


class Subscription(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_PAST_DUE = "past_due"
    STATUS_CANCELED = "canceled"
    
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAST_DUE, "Past Due"),
        (STATUS_CANCELED, "Canceled"),
    ]

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    billing_start = models.DateTimeField()
    billing_end = models.DateTimeField()
    usage_count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.tenant.name} - {self.plan.name} ({self.status})"
