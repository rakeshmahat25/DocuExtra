from core.models import WorkspaceMember

def workspace_context(request):
    if not request.user.is_authenticated:
        return {}

    user_workspaces = []
    user_role_in_workspace = None

    # Retrieve all workspaces the user has access to
    memberships = WorkspaceMember.objects.select_related("workspace", "workspace__tenant").filter(
        user=request.user
    )
    for membership in memberships:
        user_workspaces.append(membership.workspace)
        if request.workspace and membership.workspace.id == request.workspace.id:
            user_role_in_workspace = membership.role

    return {
        "active_workspace": request.workspace,
        "active_tenant": request.tenant,
        "user_workspaces": user_workspaces,
        "user_role_in_workspace": user_role_in_workspace,
    }
