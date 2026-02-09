# callManager/consumers.py
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import json

@database_sync_to_async
def get_user_manager(user):
    return getattr(user, 'manager', None)

@database_sync_to_async
def get_manager_company_id(user):
    try:
        company_id = user.manager.company.id
        return user.manager.company.id
    except (AttributeError, user.manager.RelatedObjectDoesNotExist):
        return None

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]

        # Wrap DB access in sync_to_async
        manager = await get_user_manager(user)

        if user.is_anonymous or not manager:
            await self.close()
            return

        self.company_id = await get_manager_company_id(user)
        self.group_name = f"company_{self.company_id}_notifications"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def send_notification(self, event):
        await self.send(text_data=json.dumps({
            "type": "htmx_trigger",
            "event": "notification-update"
        }))

class LaborRequestConsumer(AsyncWebsocketConsumer):
    """updates the labor request list when workers
    responds to requests. """
    async def connect(self):
        user = self.scope["user"]
        self.labor_requirement_slug = self.scope['url_route']['kwargs']['slug']

        # Wrap DB access in sync_to_async   
        manager = await get_user_manager(user)

        if user.is_anonymous or not manager:
            await self.close()
            return  
        
        self.group_name = f"labor_request_{self.labor_requirement_slug}_updates"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def labor_request_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "labor_request_update",
            "data": event.get("data", {})
        }))
