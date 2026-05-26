import os
import tempfile
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from core.models import Tenant, Workspace, User, WorkspaceMember, SubscriptionPlan, Subscription
from documents.models import Workflow, ExtractionField, Document, DocumentPage, DocumentFieldResult
from documents.ai_pipeline import process_document, evaluate_validation_rules

class DocuOCRTestCase(TestCase):
    def setUp(self):
        # 1. Setup multi-tenant workspace
        self.tenant = Tenant.objects.create(name="Acme Corp", subdomain="acme")
        self.user = User.objects.create_user(
            username="admin_user",
            email="admin@acme.com",
            password="testpassword123",
            role=User.ROLE_ADMIN
        )
        self.workspace = Workspace.objects.create(tenant=self.tenant, name="Engineering")
        self.member = WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=User.ROLE_ADMIN
        )
        
        # 2. Setup subscription
        self.plan = SubscriptionPlan.objects.create(name="Growth", price=49.00)
        self.subscription = Subscription.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            status=Subscription.STATUS_ACTIVE,
            billing_start=timezone.now(),
            billing_end=timezone.now() + timezone.timedelta(days=30)
        )

        # 3. Setup standard Invoice workflow
        self.workflow = Workflow.objects.create(
            workspace=self.workspace,
            name="Invoice Scanner",
            document_type="invoice"
        )
        self.field_sub = ExtractionField.objects.create(
            workflow=self.workflow,
            name="subtotal",
            label="Subtotal",
            data_type="number"
        )
        self.field_tax = ExtractionField.objects.create(
            workflow=self.workflow,
            name="tax_amount",
            label="Tax",
            data_type="number"
        )
        self.field_tot = ExtractionField.objects.create(
            workflow=self.workflow,
            name="total_amount",
            label="Total",
            data_type="number",
            validation_rules={"math_expression": "subtotal + tax_amount == total_amount"}
        )

    def test_tenant_onboarding(self):
        """Verifies Tenant B2B registration and relations exist."""
        self.assertEqual(self.tenant.name, "Acme Corp")
        self.assertEqual(self.workspace.tenant, self.tenant)
        self.assertEqual(self.member.user, self.user)
        self.assertEqual(self.subscription.plan.name, "Growth")

    def test_validation_rule_engine(self):
        """Verifies that the math expression validator handles true/false cases correctly."""
        # Create a document
        doc = Document.objects.create(
            workspace=self.workspace,
            workflow=self.workflow,
            name="test_invoice.png",
            file_type="png",
            extracted_json={"fields": {"subtotal": "100.00", "tax_amount": "15.00", "total_amount": "115.00"}}
        )
        
        # Run validations
        passed = evaluate_validation_rules(
            doc, 
            [self.field_sub, self.field_tax, self.field_tot], 
            doc.extracted_json["fields"]
        )
        self.assertTrue(passed)
        self.assertEqual(doc.validation_status, Document.VALIDATION_VERIFIED)

        # Update with invalid values
        doc.extracted_json = {"fields": {"subtotal": "100.00", "tax_amount": "15.00", "total_amount": "120.00"}}
        doc.save()
        passed_fail = evaluate_validation_rules(
            doc, 
            [self.field_sub, self.field_tax, self.field_tot], 
            doc.extracted_json["fields"]
        )
        self.assertFalse(passed_fail)
        self.assertEqual(doc.validation_status, Document.VALIDATION_FAILED)

    def test_document_pipeline_integration(self):
        """Verifies local simulator runs end-to-end processing and generates field results."""
        # Mock file upload
        test_file = SimpleUploadedFile(
            "invoice_123.pdf", 
            b"%PDF-1.4 mock pdf text contents containing Invoice Number: INV-99\nSubtotal: 200.00\nTax: 20.00\nTotal: 220.00", 
            content_type="application/pdf"
        )
        
        doc = Document.objects.create(
            workspace=self.workspace,
            workflow=self.workflow,
            name="invoice_123.pdf",
            file=test_file,
            file_type="pdf"
        )
        
        # Execute processing pipeline directly
        process_document(doc.id)
        
        doc.refresh_from_db()
        # Verify status is updated
        self.assertIn(doc.status, [Document.STATUS_COMPLETED, Document.STATUS_HUMAN_REVIEW])
        
        # Verify fields were populated
        results = DocumentFieldResult.objects.filter(document=doc)
        self.assertTrue(results.exists())
        
        inv_num_res = results.filter(field_name="total_amount").first()
        self.assertIsNotNone(inv_num_res)

    def test_api_upload_endpoint(self):
        """Tests DRF POST upload endpoint with API token headers."""
        client = Client()
        
        # Prepare test file upload
        test_file = SimpleUploadedFile("kyc_doc.png", b"mock image payload bytes", content_type="image/png")
        
        # Call upload API with organization header
        url = reverse("api:api_upload")
        headers = {
            "HTTP_X_ORGANIZATION_API_KEY": str(self.tenant.api_key),
            "HTTP_X_WORKSPACE_ID": str(self.workspace.id)
        }
        
        response = client.post(
            url,
            {"file": test_file, "workflow_id": self.workflow.id},
            **headers
        )
        
        self.assertEqual(response.status_code, 201)
        res_data = response.json()
        self.assertIn("document_id", res_data)
        self.assertEqual(res_data["status"], "pending")
