# callManager/consumers.py
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import json
import logging

# Create a logger instance
logger = logging.getLogger('callManager')

@database_sync_to_async
def get_user_manager(user):
    return getattr(user, 'manager', None)

@database_sync_to_async
def get_manager_company_id(user):
    try:
        company_id = user.manager.company.id
        logger.debug(f"Company ID: {company_id}")
        return user.manager.company.id
    except (AttributeError, user.manager.RelatedObjectDoesNotExist):
        logger.error(f"User {user} does not have a manager or company.")
        return None

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        logger.info(f"User {user} connected to notifications.")

        # Wrap DB access in sync_to_async
        manager = await get_user_manager(user)

        if user.is_anonymous or not manager:
            logger.warning(f"User {user} is anonymous or does not have a manager. Closing connection.")
            await self.close()
            return

        self.company_id = await get_manager_company_id(user)
        self.group_name = f"company_{self.company_id}_notifications"
        logger.info(f"Adding user {user} to group {self.group_name}")

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"User {user} added to group {self.group_name}")

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            logger.info(f"Removing user from group {self.group_name}")
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def send_notification(self, event):
        logger.debug(f"Sending notification to {self.group_name}")
        await self.send(text_data=json.dumps({
            "type": "htmx_trigger",
            "event": "notification-update"
        }))
