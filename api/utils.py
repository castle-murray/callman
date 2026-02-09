from django.conf import settings


def frontend_url(request, path):
    """Build a full URL using the React frontend's origin.

    Reads X-Frontend-Origin header sent by the React Axios instance.
    Falls back to settings.FRONTEND_URL (for non-browser callers like Twilio webhooks).
    """
    origin = request.META.get('HTTP_X_FRONTEND_ORIGIN') or settings.FRONTEND_URL


def get_client_ip(request):
    """Get the real client IP address, considering X-Forwarded-For header."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
    return f"{origin.rstrip('/')}{path}"
