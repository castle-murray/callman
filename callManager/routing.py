from django.urls import re_path
from callManager.consumers import (
        NotificationConsumer,
        LaborRequestConsumer,
        )

websocket_urlpatterns = [
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
    re_path(r"ws/labor-requests/(?P<slug>[\w-]+)/$", LaborRequestConsumer.as_asgi()),
]
