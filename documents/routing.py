from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/documents/(?P<workspace_id>\d+)/$", consumers.DocumentProcessConsumer.as_asgi()),
]
