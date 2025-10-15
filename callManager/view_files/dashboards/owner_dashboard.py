
#models
from time import sleep
from callManager.models import (
        ManagerInvitation,
        )
#forms
from callManager.forms import (
        CompanyHoursForm,
        CompanyForm,
        )
# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
import logging

from callManager.views import log_sms, send_message

# Create a logger instance
logger = logging.getLogger('callManager')

@login_required
def owner_dashboard(request):
    if not hasattr(request.user, 'owner'):
        return redirect('login')
    owner = request.user.owner
    company = owner.company
    if request.method == "POST":
        if 'phone' in request.POST:
            phone = request.POST.get('phone')
            if phone:
                invitation = ManagerInvitation.objects.create(company=company, phone=phone)
                registration_url = request.build_absolute_uri(reverse('register_manager', args=[str(invitation.token)]))
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                message_body = f'You are invited to become a manager for {company.name}. Register: {registration_url}'
                if settings.TWILIO_ENABLED == 'enabled' and client:
                    try:
                        client.messages.create(
                            body=message_body,
                            from_=settings.TWILIO_PHONE_NUMBER,
                            to=phone)
                        log_sms(company)
                        messages.success(request, f"Invitation sent to {phone}.")
                    except TwilioRestException as e:
                        messages.error(request, f"Failed to send invitation: {str(e)}")
                else:
                    log_sms(company)
                    print(message_body)
                    messages.success(request, f"Invitation printed for {phone}.")
            else:
                messages.error(request, "Please provide a phone number.")
        else:
            form = CompanyForm(request.POST, instance=company)
            if form.is_valid():
                form.save()
                messages.success(request, "Company information updated successfully.")
            else:
                messages.error(request, "Failed to update company information.")
    form = CompanyForm(instance=company)
    time_form = CompanyHoursForm(instance=company)
    context = {'form': form, 'company': company, 'time_form': time_form}
    return render(request, 'callManager/owner_dashboard.html', context)
