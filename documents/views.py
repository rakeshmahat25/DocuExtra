import os
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from core.models import User
from .models import Workflow, ExtractionField, Document, DocumentPage, DocumentFieldResult
from .tasks import trigger_document_processing
from .ai_pipeline import evaluate_validation_rules

@login_required
def workflow_list(request):
    """Lists all active custom workflows inside the workspace."""
    workspace = request.workspace
    if not workspace:
        return redirect("core:create_workspace")

    workflows = Workflow.objects.filter(workspace=workspace).prefetch_related("fields")
    return render(request, "documents/workflow_list.html", {"workflows": workflows})


@login_required
def workflow_create(request):
    """Allows admins to configure custom prompts and dynamic field schemas."""
    workspace = request.workspace
    # Check permissions
    if request.user.role != User.ROLE_ADMIN:
        messages.error(request, "Only administrators can configure workflows.")
        return redirect("documents:workflow_list")

    if request.method == "POST":
        name = request.POST.get("name")
        doc_type = request.POST.get("document_type")
        prompt = request.POST.get("system_prompt_override", "")
        
        # Capture fields lists
        field_keys = request.POST.getlist("field_key[]")
        field_labels = request.POST.getlist("field_label[]")
        field_types = request.POST.getlist("field_type[]")
        field_required = request.POST.getlist("field_required[]")
        
        if name and doc_type:
            workflow = Workflow.objects.create(
                workspace=workspace,
                name=name,
                document_type=doc_type,
                system_prompt_override=prompt
            )

            # Create ExtractionField rules
            for i in range(len(field_keys)):
                key = field_keys[i].strip()
                label = field_labels[i].strip()
                dtype = field_types[i]
                req = str(i) in field_required or field_keys[i] in field_required # Checkbox list matching
                
                if key and label:
                    # Parse mathematical formulas into validation rules if total
                    rules = {}
                    if key == "total_amount":
                        rules = {"math_expression": "subtotal + tax_amount == total_amount"}
                    
                    ExtractionField.objects.create(
                        workflow=workflow,
                        name=key,
                        label=label,
                        data_type=dtype,
                        is_required=req,
                        validation_rules=rules
                    )

            messages.success(request, f"Custom AI Workflow '{name}' initialized successfully!")
            return redirect("documents:workflow_list")
        else:
            messages.error(request, "Workflow name and document type are required.")

    return render(request, "documents/workflow_create.html")


@login_required
def workflow_delete(request, workflow_id):
    """Deletes workflow templates."""
    workflow = get_object_or_404(Workflow, id=workflow_id, workspace=request.workspace)
    if request.user.role != User.ROLE_ADMIN:
        messages.error(request, "Admin permission required.")
        return redirect("documents:workflow_list")
        
    name = workflow.name
    workflow.delete()
    messages.success(request, f"Workflow '{name}' deleted.")
    return redirect("documents:workflow_list")


@login_required
@csrf_exempt
def document_upload(request):
    """
    Handles B2B async document upload requests.
    Creates Document entry and starts async background pipeline (Celery or Thread fallback).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    workspace = request.workspace
    if not workspace:
        return JsonResponse({"error": "Workspace not resolved"}, status=400)

    file_obj = request.FILES.get("file")
    if not file_obj:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    filename = file_obj.name
    ext = os.path.splitext(filename)[1].replace(".", "").lower()
    
    # Validate extension
    allowed_exts = ["pdf", "png", "jpg", "jpeg", "tiff", "heic"]
    if ext not in allowed_exts:
        return JsonResponse({"error": f"Unsupported extension: {ext}"}, status=400)

    # 1. Create Document model
    document = Document.objects.create(
        workspace=workspace,
        name=filename,
        file=file_obj,
        file_type=ext,
        status=Document.STATUS_PENDING
    )

    # 2. Trigger asynchronous background process (using Celery/Thread fallback)
    trigger_document_processing(document.id)

    return JsonResponse({
        "message": "File enqueued for AI extraction",
        "document": {
            "id": document.id,
            "name": document.name,
            "file_type": document.file_type,
            "status": document.status,
            "created_at": document.created_at.strftime("%Y-%m-%d %H:%M")
        }
    }, status=201)


@login_required
def review_detail(request, document_id):
    """Renders the Side-by-side Human Review Dashboard verification panel."""
    document = get_object_or_404(Document, id=document_id, workspace=request.workspace)
    pages = document.pages.all()
    field_results = document.field_results.all()
    
    # Audit log entry for opening document
    from analytics.models import AuditLog
    AuditLog.objects.create(
        workspace=request.workspace,
        user=request.user,
        action="VIEW_DOCUMENT_REVIEW",
        details={"document_id": document.id, "name": document.name}
    )

    context = {
        "document": document,
        "pages": pages,
        "field_results": field_results,
    }
    return render(request, "review/dashboard.html", context)


@login_required
def review_submit(request, document_id):
    """
    Submits manual corrections from reviewer.
    Saves new values, runs re-validation rules, updates audit history, and completes document.
    """
    document = get_object_or_404(Document, id=document_id, workspace=request.workspace)
    if request.method != "POST":
        return redirect("documents:review_detail", document_id=document.id)

    # Resolve active workflow fields
    workflow = document.workflow
    if not workflow:
        messages.error(request, "No extraction workflow mapped to document.")
        return redirect("core:dashboard")

    fields = workflow.fields.all()
    
    # Prepare data dict of corrected inputs
    corrections = {}
    for field in fields:
        form_val = request.POST.get(field.name)
        # Update DocumentFieldResult
        result = DocumentFieldResult.objects.filter(document=document, field_name=field.name).first()
        if result:
            # Save correction
            result.corrected_value = form_val
            result.save()
            corrections[field.name] = form_val

    # Run mathematical and validation check rules again over corrected dataset
    evaluate_validation_rules(document, fields, corrections)

    # Save final reviewer context
    document.status = Document.STATUS_COMPLETED
    document.reviewer = request.user
    document.reviewed_at = timezone.now()
    document.save(update_fields=["status", "reviewer", "reviewed_at"])

    # Create Audit Log
    from analytics.models import AuditLog
    AuditLog.objects.create(
        workspace=request.workspace,
        user=request.user,
        action="SUBMIT_DOCUMENT_CORRECTION",
        details={"document_id": document.id, "name": document.name}
    )

    # Notify dashboard socket
    from .ai_pipeline import trigger_websocket_update
    trigger_websocket_update(document)

    messages.success(request, f"Document '{document.name}' verified and locked successfully!")
    return redirect("core:dashboard")
