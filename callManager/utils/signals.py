import logging
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

logger  = logging.getLogger('django_failed_login')

@receiver(user_login_failed)
def log_failed_login(sender, credentials, request, **kwargs):
    if request:
        ip = request.META.get('REMOTE_ADDR')  # With real_ip, this is the real client IP
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        username = credentials.get('username', '<unknown>')
        logger.warning(f"Failed login attempt for username='{username}' from IP={ip} UA='{user_agent}'")

