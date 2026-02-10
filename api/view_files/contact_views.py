from django.conf import settings
from django.core.mail import get_connection, EmailMessage
from django.template.loader import render_to_string
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle


class ContactFormThrottle(AnonRateThrottle):
    rate = '5/hour'


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ContactFormThrottle])
def contact_form(request):
    data = request.data
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    company = data.get('company', '').strip()
    message = data.get('message', '').strip()

    errors = {}
    if not name:
        errors['name'] = 'Name is required.'
    if not email:
        errors['email'] = 'Email is required.'
    if not company:
        errors['company'] = 'Company is required.'
    if not message:
        errors['message'] = 'Message is required.'

    if errors:
        return Response({'status': 'error', 'errors': errors}, status=400)

    subject = f"Contact Form: {name} from {company}"
    context = {
        'name': name,
        'email': email,
        'phone': phone or 'Not provided',
        'company': company,
        'message': message,
    }

    try:
        connection = get_connection(
            host=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=settings.SALES_EMAIL_HOST_USER,
            password=settings.SALES_EMAIL_HOST_PASSWORD,
            use_tls=settings.EMAIL_USE_TLS,
        )
        # Internal notification to sales team
        body = render_to_string('callManager/emails/contact_form_email.html', context)
        internal_msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.SALES_EMAIL_HOST_USER,
            to=['sales@callman.work'],
            connection=connection,
        )
        internal_msg.content_subtype = 'html'

        # Auto-reply to the person who submitted the form
        autoreply_body = render_to_string('callManager/emails/contact_form_autoreply.html', context)
        autoreply_msg = EmailMessage(
            subject='Thank you for contacting CallMan',
            body=autoreply_body,
            from_email=settings.SALES_EMAIL_HOST_USER,
            to=[email],
            connection=connection,
        )
        autoreply_msg.content_subtype = 'html'

        internal_msg.send()
        autoreply_msg.send()
        return Response({'status': 'success', 'message': 'Your message has been sent.'})
    except Exception:
        return Response(
            {'status': 'error', 'message': 'Failed to send message. Please try again later.'},
            status=500,
        )
