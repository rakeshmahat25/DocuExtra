from core.models import Workspace, WorkspaceMember

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.workspace = None

        # 1. API key authentication takes care of setting workspace in API endpoints (handled separately in auth),
        # but we can also resolve via custom headers for convenience.
        workspace_id_header = request.headers.get("X-Workspace-ID")
        tenant_key_header = request.headers.get("X-Tenant-Key")

        if workspace_id_header:
            try:
                workspace = Workspace.objects.select_related("tenant").get(id=workspace_id_header)
                request.workspace = workspace
                request.tenant = workspace.tenant
            except (Workspace.DoesNotExist, ValueError):
                pass
        
        # 2. Session-based workspace resolution (for browser users)
        elif request.user.is_authenticated:
            session_workspace_id = request.session.get("active_workspace_id")
            if session_workspace_id:
                try:
                    workspace = Workspace.objects.select_related("tenant").get(
                        id=session_workspace_id,
                        members__user=request.user
                    )
                    request.workspace = workspace
                    request.tenant = workspace.tenant
                except Workspace.DoesNotExist:
                    # Clean up invalid session workspace
                    del request.session["active_workspace_id"]

            # If no workspace in session, fall back to the first membership
            if not request.workspace:
                membership = WorkspaceMember.objects.select_related("workspace", "workspace__tenant").filter(
                    user=request.user
                ).first()
                if membership:
                    request.workspace = membership.workspace
                    request.tenant = membership.workspace.tenant
                    request.session["active_workspace_id"] = membership.workspace.id

        response = self.get_response(request)
        return response
