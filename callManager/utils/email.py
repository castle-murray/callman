from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

def send_custom_email(subject, to_email, template_name, context):
    try:
        message = render_to_string(template_name, context)
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            html_message=message
        )
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {str(e)}")
        return False
