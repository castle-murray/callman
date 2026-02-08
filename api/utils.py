from django.conf import settings


def frontend_url(request, path):
    """Build a full URL using the React frontend's origin.

    Reads X-Frontend-Origin header sent by the React Axios instance.
    Falls back to settings.FRONTEND_URL (for non-browser callers like Twilio webhooks).
    """
    origin = request.META.get('HTTP_X_FRONTEND_ORIGIN') or settings.FRONTEND_URL
    return f"{origin.rstrip('/')}{path}"
