import logging
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

# Dedicated logger name
logger = logging.getLogger('django.security.failed_login')

@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    if request is None:
        return  # Rare edge case

    # With Cloudflare + real_ip_module, REMOTE_ADDR is the real client IP
    ip = request.META.get('REMOTE_ADDR', 'unknown')
    username = credentials.get('username') or '<unknown>'
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:200]  # Truncate if too long

    logger.warning(
        f"Failed login attempt username='{username}' ip={ip} ua='{user_agent}'"
    )
