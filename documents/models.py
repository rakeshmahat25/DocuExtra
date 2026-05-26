from django.db import models
from django.conf import settings
from core.models import Workspace

class Workflow(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="workflows")
    name = models.CharField(max_length=100)
    document_type = models.CharField(
        max_length=50,
        help_text="Standard types: invoice, receipt, kyc_id, bank_statement, medical, custom"
    )
    system_prompt_override = models.TextField(
        blank=True,
        help_text="Custom instructions to the LLM (e.g., 'Extract the total amount only if it exceeds $100')"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.document_type})"


class ExtractionField(models.Model):
    DATA_TYPES = [
        ("text", "Text"),
        ("number", "Number / Currency"),
        ("date", "Date"),
        ("boolean", "Boolean (Checkbox/Stamp)"),
        ("table", "Table / List of Items"),
    ]

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=50, help_text="JSON key representing the field (e.g. invoice_number)")
    label = models.CharField(max_length=100, help_text="Friendly label shown in review dashboard (e.g. Invoice Number)")
    data_type = models.CharField(max_length=20, choices=DATA_TYPES, default="text")
    is_required = models.BooleanField(default=True)
    validation_rules = models.JSONField(
        default=dict,
        blank=True,
        help_text="Custom validations (e.g., {'regex': '^[A-Z]{3}\\d{4}$', 'min_value': 0, 'math_expression': 'subtotal + tax == total'})"
    )
    default_value = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.workflow.name} - {self.label} ({self.data_type})"


class Document(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PREPROCESSING = "preprocessing"
    STATUS_EXTRACTING = "extracting"
    STATUS_VALIDATING = "validating"
    STATUS_HUMAN_REVIEW = "human_review"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PREPROCESSING, "Preprocessing"),
        (STATUS_EXTRACTING, "Extracting"),
        (STATUS_VALIDATING, "Validating"),
        (STATUS_HUMAN_REVIEW, "Human Review"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    VALIDATION_PENDING = "pending"
    VALIDATION_VERIFIED = "verified"
    VALIDATION_WARNING = "warning"
    VALIDATION_FAILED = "failed"

    VALIDATION_CHOICES = [
        (VALIDATION_PENDING, "Pending"),
        (VALIDATION_VERIFIED, "Verified"),
        (VALIDATION_WARNING, "Warning"),
        (VALIDATION_FAILED, "Failed"),
    ]

    FRAUD_PASSED = "passed"
    FRAUD_REVIEW = "review"
    FRAUD_FAILED = "failed"

    FRAUD_CHOICES = [
        (FRAUD_PASSED, "Passed"),
        (FRAUD_REVIEW, "Needs Review"),
        (FRAUD_FAILED, "Flagged Fraudulent"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="documents")
    workflow = models.ForeignKey(Workflow, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    file_type = models.CharField(max_length=20) # pdf, png, jpg, jpeg, tiff
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    confidence_score = models.FloatField(default=0.0, help_text="Average field extraction confidence (0.0 to 1.0)")
    extracted_json = models.JSONField(default=dict, blank=True)
    raw_text = models.TextField(blank=True, help_text="Consolidated full extracted OCR text")
    
    validation_status = models.CharField(max_length=20, choices=VALIDATION_CHOICES, default=VALIDATION_PENDING)
    fraud_status = models.CharField(max_length=20, choices=FRAUD_CHOICES, default=FRAUD_PASSED)
    fraud_details = models.JSONField(default=dict, blank=True)
    
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_documents"
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class DocumentPage(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    page_number = models.IntegerField()
    image = models.ImageField(upload_to="document_pages/%Y/%m/%d/")
    raw_text = models.TextField(blank=True)
    confidence_score = models.FloatField(default=1.0)

    class Meta:
        ordering = ["page_number"]

    def __str__(self):
        return f"{self.document.name} - Page {self.page_number}"


class DocumentFieldResult(models.Model):
    VALIDATION_CHOICES = [
        ("verified", "Verified"),
        ("warning", "Warning"),
        ("failed", "Failed"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="field_results")
    field_name = models.CharField(max_length=50) # key
    field_label = models.CharField(max_length=100) # display label
    
    extracted_value = models.TextField(blank=True, null=True)
    corrected_value = models.TextField(blank=True, null=True)
    confidence = models.FloatField(default=1.0)
    
    validation_status = models.CharField(max_length=20, choices=VALIDATION_CHOICES, default="verified")
    validation_message = models.TextField(blank=True)
    
    # Bounding box coordinates for front-end highlights: e.g. {"page": 1, "x0": 10, "y0": 20, "x1": 50, "y1": 60}
    bounding_box = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.document.name} - {self.field_name}: {self.corrected_value or self.extracted_value}"


class FraudCheck(models.Model):
    RISK_CHOICES = [
        ("low", "Low Risk"),
        ("medium", "Medium Risk"),
        ("high", "High Risk"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="fraud_checks")
    rule_name = models.CharField(max_length=100)
    risk_level = models.CharField(max_length=20, choices=RISK_CHOICES, default="low")
    description = models.TextField()
    passed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document.name} - {self.rule_name} (Passed: {self.passed})"
