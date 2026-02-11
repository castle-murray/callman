from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware


@database_sync_to_async
def get_user_from_token(token_key):
    from rest_framework.authtoken.models import Token
    try:
        return Token.objects.get(key=token_key).user
    except Token.DoesNotExist:
        return None


class TokenAuthMiddleware(BaseMiddleware):
    """Authenticate WebSocket connections using a DRF token in the query string."""

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token_key = params.get("token", [None])[0]

        if token_key:
            user = await get_user_from_token(token_key)
            if user:
                scope["user"] = user

        return await super().__call__(scope, receive, send)
