import json
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.models import Tenant, Workspace, User
from documents.models import Document, Workflow, DocumentFieldResult
from documents.tasks import trigger_document_processing
from documents.ai_pipeline import evaluate_validation_rules
from .models import WebhookEndpoint, WebhookDeliveryLog

# REST API Endpoint: Document Upload
class DocumentUploadAPI(APIView):
    """
    POST /api/v1/documents/upload/
    Uploads a new document file (PDF or image) for AI processing.
    """
    def post(self, request):
        workspace = getattr(request, "workspace", None)
        if not workspace:
            return Response({"error": "Active workspace could not be resolved."}, status=status.HTTP_400_BAD_REQUEST)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        workflow_id = request.data.get("workflow_id")
        workflow = None
        if workflow_id:
            workflow = get_object_or_404(Workflow, id=workflow_id, workspace=workspace)

        # Get file type
        import os
        filename = file_obj.name
        ext = os.path.splitext(filename)[1].replace(".", "").lower()
        
        if ext not in ["pdf", "png", "jpg", "jpeg", "tiff"]:
            return Response({"error": f"Unsupported extension: {ext}"}, status=status.HTTP_400_BAD_REQUEST)

        document = Document.objects.create(
            workspace=workspace,
            workflow=workflow,
            name=filename,
            file=file_obj,
            file_type=ext,
            status=Document.STATUS_PENDING
        )

        # Start AI processing
        trigger_document_processing(document.id)

        return Response({
            "message": "File uploaded and enqueued successfully.",
            "document_id": document.id,
            "status": document.status,
            "file_type": document.file_type
        }, status=status.HTTP_201_CREATED)


# REST API Endpoint: Document Extraction Details
class DocumentDetailAPI(APIView):
    """
    GET /api/v1/documents/<id>/
    Retrieves the extracted fields, status, and fraud details of a document.
    """
    def get(self, request, document_id):
        workspace = getattr(request, "workspace", None)
        document = get_object_or_404(Document, id=document_id, workspace=workspace)

        fields = {}
        for res in document.field_results.all():
            fields[res.field_name] = {
                "label": res.field_label,
                "extracted_value": res.extracted_value,
                "corrected_value": res.corrected_value,
                "confidence": res.confidence,
                "validation_status": res.validation_status,
                "validation_message": res.validation_message
            }

        return Response({
            "document_id": document.id,
            "name": document.name,
            "status": document.status,
            "confidence_score": document.confidence_score,
            "validation_status": document.validation_status,
            "fraud_status": document.fraud_status,
            "fraud_details": document.fraud_details,
            "extracted_fields": fields,
            "raw_text": document.raw_text,
            "created_at": document.created_at,
            "processed_at": document.processed_at
        }, status=status.HTTP_200_OK)


# REST API Endpoint: Manual Verify and Correct Data
class DocumentVerifyAPI(APIView):
    """
    POST /api/v1/documents/<id>/verify/
    Applies manual corrections and verifies data via REST integrations.
    """
    def post(self, request, document_id):
        workspace = getattr(request, "workspace", None)
        document = get_object_or_404(Document, id=document_id, workspace=workspace)
        workflow = document.workflow

        if not workflow:
            return Response({"error": "No workflow mapped to document."}, status=status.HTTP_400_BAD_REQUEST)

        # Body: {"fields": {"invoice_number": "NEW123"}}
        corrections = request.data.get("fields", {})
        if not corrections:
            return Response({"error": "No corrections dictionary provided."}, status=status.HTTP_400_BAD_REQUEST)

        for key, val in corrections.items():
            result = DocumentFieldResult.objects.filter(document=document, field_name=key).first()
            if result:
                result.corrected_value = val
                result.save()

        # Re-run rule engine
        evaluate_validation_rules(document, workflow.fields.all(), corrections)

        document.status = Document.STATUS_COMPLETED
        document.reviewer = request.user if request.user.is_authenticated else None
        document.reviewed_at = timezone.now()
        document.save(update_fields=["status", "reviewer", "reviewed_at"])

        # WebSocket trigger update
        from documents.ai_pipeline import trigger_websocket_update
        trigger_websocket_update(document)

        return Response({
            "message": "Document verified successfully.",
            "document_id": document.id,
            "status": document.status,
            "validation_status": document.validation_status
        }, status=status.HTTP_200_OK)


# Developer Dashboard & Integration Page HTML View
@login_required
def integration_guide(request):
    """
    Renders developer API management page.
    Generates copy-paste code scripts for python, javascript, curl.
    Lists webhook endpoints and delivery history logs.
    """
    workspace = request.workspace
    if not workspace:
        return redirect("core:create_workspace")

    endpoints = WebhookEndpoint.objects.filter(workspace=workspace)
    logs = WebhookDeliveryLog.objects.filter(endpoint__workspace=workspace).order_by("-sent_at")[:15]

    # Webhook Endpoint creation handling
    if request.method == "POST" and "add_webhook" in request.POST:
        # Check permissions
        if request.user.role != User.ROLE_ADMIN:
            messages.error(request, "Only admins can add webhooks.")
            return redirect("api:integration_guide")

        url = request.POST.get("url")
        events = request.POST.getlist("events[]")
        
        if url:
            WebhookEndpoint.objects.create(
                workspace=workspace,
                url=url,
                events=events or ["document.processed"]
            )
            messages.success(request, f"Webhook endpoint '{url}' registered!")
            return redirect("api:integration_guide")
        else:
            messages.error(request, "URL is required.")

    # Create dynamic code snippets with active keys
    api_key = workspace.tenant.api_key
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host()
    base_api_url = f"{scheme}://{host}/api/v1"

    snippets = {
        "curl": (
            f"curl -X POST {base_api_url}/documents/upload/ \\\n"
            f"  -H 'X-Organization-API-Key: {api_key}' \\\n"
            f"  -F 'file=@/path/to/document.pdf'"
        ),
        "python": (
            "import requests\n\n"
            f"url = '{base_api_url}/documents/upload/'\n"
            f"headers = {{'X-Organization-API-Key': '{api_key}'}}\n"
            "files = {'file': open('invoice.pdf', 'rb')}\n\n"
            "response = requests.post(url, headers=headers, files=files)\n"
            "print(response.json())"
        ),
        "node": (
            "const axios = require('axios');\n"
            "const fs = require('fs');\n"
            "const FormData = require('form-data');\n\n"
            "const form = new FormData();\n"
            "form.append('file', fs.createReadStream('invoice.pdf'));\n\n"
            f"axios.post('{base_api_url}/documents/upload/', form, {{\n"
            "  headers: {\n"
            f"    'X-Organization-API-Key': '{api_key}',\n"
            "    ...form.getHeaders()\n"
            "  }\n"
            "}).then(res => console.log(res.data));"
        )
    }

    context = {
        "api_key": api_key,
        "endpoints": endpoints,
        "delivery_logs": logs,
        "snippets": snippets
    }
    return render(request, "api/integration_guide.html", context)


@login_required
def delete_webhook(request, endpoint_id):
    """Deletes webhook endpoint configurations."""
    endpoint = get_object_or_404(WebhookEndpoint, id=endpoint_id, workspace=request.workspace)
    if request.user.role != User.ROLE_ADMIN:
        messages.error(request, "Permission denied.")
        return redirect("api:integration_guide")

    url = endpoint.url
    endpoint.delete()
    messages.success(request, f"Webhook endpoint '{url}' deleted.")
    return redirect("api:integration_guide")
