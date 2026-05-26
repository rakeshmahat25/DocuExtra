from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from core.models import Tenant, WorkspaceMember

class APIKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        api_key_header = request.headers.get("X-Organization-API-Key")
        if not api_key_header:
            return None

        try:
            tenant = Tenant.objects.get(api_key=api_key_header)
        except (Tenant.DoesNotExist, ValueError):
            raise AuthenticationFailed("Invalid Organization API Key.")

        # Find the primary workspace of the tenant
        workspace = tenant.workspaces.first()
        if not workspace:
            raise AuthenticationFailed("Tenant has no workspaces configured.")

        # Find an administrator user in the workspace to act as actor
        admin_member = WorkspaceMember.objects.filter(workspace=workspace, role="admin").first()
        if not admin_member:
            raise AuthenticationFailed("No workspace administrator available for API authorization.")

        # Attach solved workspaces & tenants to requests
        request.workspace = workspace
        request.tenant = tenant
        
        return (admin_member.user, None)
