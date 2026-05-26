from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("signup/", views.register_onboarding, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("workspaces/create/", views.create_workspace, name="create_workspace"),
    path("workspaces/switch/<int:workspace_id>/", views.switch_workspace, name="switch_workspace"),
    path("workspaces/team/", views.team_settings, name="team_settings"),
]
