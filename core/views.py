from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.forms import AuthenticationForm
from core.models import Tenant, Workspace, WorkspaceMember, User, SubscriptionPlan, Subscription
from documents.models import Document, Workflow

def register_onboarding(request):
    """
    Handles B2B onboarding. Registers user, tenant, workspace,
    and sets up default free subscription.
    """
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        email = request.POST.get("email")
        username = request.POST.get("username")
        password = request.POST.get("password")
        company_name = request.POST.get("company_name")
        subdomain = request.POST.get("subdomain", "").lower().strip()

        if not (email and username and password and company_name and subdomain):
            messages.error(request, "Please fill in all required fields.")
            return render(request, "registration/signup.html")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
            return render(request, "registration/signup.html")

        if Tenant.objects.filter(subdomain=subdomain).exists():
            messages.error(request, "Subdomain already registered. Try another name.")
            return render(request, "registration/signup.html")

        try:
            with transaction.atomic():
                # 1. Create Tenant
                tenant = Tenant.objects.create(
                    name=company_name,
                    subdomain=subdomain
                )

                # 2. Create User
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    role=User.ROLE_ADMIN
                )

                # 3. Create Default Workspace
                workspace = Workspace.objects.create(
                    tenant=tenant,
                    name="Default Workspace",
                    description="Main operational workspace."
                )

                # 4. Map User to Workspace
                WorkspaceMember.objects.create(
                    workspace=workspace,
                    user=user,
                    role=User.ROLE_ADMIN
                )

                # 5. Get or Create standard Free subscription plan
                plan, _ = SubscriptionPlan.objects.get_or_create(
                    name="Free Tier",
                    defaults={"price": 0.00, "max_documents_per_month": 100}
                )

                # 6. Assign Subscription
                Subscription.objects.create(
                    tenant=tenant,
                    plan=plan,
                    status=Subscription.STATUS_ACTIVE,
                    billing_start=timezone.now(),
                    billing_end=timezone.now() + timedelta(days=30)
                )

            # Auto log in the user
            auth_login(request, user)
            request.session["active_workspace_id"] = workspace.id
            messages.success(request, f"Welcome to DocuOCR, {username}! Workspace initialized.")
            return redirect("core:dashboard")
            
        except Exception as e:
            messages.error(request, f"An error occurred during onboarding: {str(e)}")
            return render(request, "registration/signup.html")

    return render(request, "registration/signup.html")


def login_view(request):
    """Custom login view utilizing session workspace resolution."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")
        
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            
            # Resolve workspace
            membership = WorkspaceMember.objects.select_related("workspace").filter(user=user).first()
            if membership:
                request.session["active_workspace_id"] = membership.workspace.id
                
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect("core:dashboard")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
        
    return render(request, "registration/login.html", {"form": form})


def logout_view(request):
    """Logs out the user and cleans up workspace sessions."""
    auth_logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("core:login")


@login_required
def dashboard(request):
    """
    Renders the operational workspace dashboard.
    Lists documents, workflows, uploader panel, and metrics.
    """
    workspace = request.workspace
    if not workspace:
        # Prompt user to create a workspace if they don't have one
        return redirect("core:create_workspace")

    # Fetch Workspace Documents
    documents = Document.objects.filter(workspace=workspace).order_by("-created_at")
    workflows = Workflow.objects.filter(workspace=workspace, is_active=True)

    # Compute operational statistics
    total_docs = documents.count()
    completed_docs = documents.filter(status=Document.STATUS_COMPLETED).count()
    failed_docs = documents.filter(status=Document.STATUS_FAILED).count()
    fraud_warnings = documents.filter(fraud_status__in=[Document.FRAUD_REVIEW, Document.FRAUD_FAILED]).count()
    
    # Calculate accuracy
    if completed_docs > 0:
        avg_confidence = int(sum(d.confidence_score for d in documents.filter(status=Document.STATUS_COMPLETED)) / completed_docs * 100)
    else:
        avg_confidence = 100

    stats = {
        "total_documents": total_docs,
        "completed": completed_docs,
        "failed": failed_docs,
        "fraud_alerts": fraud_warnings,
        "accuracy_score": avg_confidence,
    }

    context = {
        "documents": documents,
        "workflows": workflows,
        "stats": stats,
    }
    return render(request, "core/dashboard.html", context)


@login_required
def create_workspace(request):
    """Creates a new workspace under the user's resolved B2B tenant."""
    # Find user's resolved tenant from existing workspaces, or get the first
    first_member = WorkspaceMember.objects.select_related("workspace", "workspace__tenant").filter(user=request.user).first()
    if not first_member:
        # If user has no workspace, let's create a placeholder tenant
        tenant = Tenant.objects.create(name=f"{request.user.username} Org", subdomain=f"{request.user.username}-org")
    else:
        tenant = first_member.workspace.tenant

    if request.method == "POST":
        name = request.POST.get("name")
        desc = request.POST.get("description", "")
        
        if name:
            workspace = Workspace.objects.create(
                tenant=tenant,
                name=name,
                description=desc
            )
            # Add creator as Admin
            WorkspaceMember.objects.create(
                workspace=workspace,
                user=request.user,
                role=User.ROLE_ADMIN
            )
            request.session["active_workspace_id"] = workspace.id
            messages.success(request, f"Workspace '{name}' created successfully!")
            return redirect("core:dashboard")
        else:
            messages.error(request, "Workspace name is required.")

    return render(request, "core/create_workspace.html")


@login_required
@require_POST
def switch_workspace(request, workspace_id):
    """Switch user's active session workspace."""
    try:
        workspace = Workspace.objects.get(id=workspace_id, members__user=request.user)
        request.session["active_workspace_id"] = workspace.id
        messages.success(request, f"Switched to workspace: {workspace.name}")
    except Workspace.DoesNotExist:
        messages.error(request, "Workspace not found or access denied.")
        
    return redirect("core:dashboard")


@login_required
def team_settings(request):
    """Lists workspace team members and allows adding new members."""
    workspace = request.workspace
    if not workspace:
        return redirect("core:create_workspace")
        
    memberships = WorkspaceMember.objects.select_related("user").filter(workspace=workspace)
    
    if request.method == "POST":
        # Check permissions - only workspace admins can invite members
        admin_member = WorkspaceMember.objects.filter(workspace=workspace, user=request.user, role=User.ROLE_ADMIN).exists()
        if not admin_member:
            messages.error(request, "Only workspace administrators can add members.")
            return redirect("core:team_settings")

        email = request.POST.get("email")
        username = request.POST.get("username")
        role = request.POST.get("role", User.ROLE_OPERATOR)
        
        if email and username:
            if User.objects.filter(username=username).exists():
                user = User.objects.get(username=username)
            else:
                # Create a user with temporary password
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password="TempPassword123!",
                    role=role
                )
                
            # Check if already member
            if WorkspaceMember.objects.filter(workspace=workspace, user=user).exists():
                messages.warning(request, f"User {username} is already a member.")
            else:
                WorkspaceMember.objects.create(
                    workspace=workspace,
                    user=user,
                    role=role
                )
                messages.success(request, f"Added user {username} successfully! (Temp Password: TempPassword123!)")
        else:
            messages.error(request, "Username and Email are required.")
            
        return redirect("core:team_settings")
        
    return render(request, "core/team_settings.html", {"memberships": memberships})
