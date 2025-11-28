
#models
from callManager.models import (
        Worker,
        StewardInvitation,
        )
#forms

# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q 
from django.conf import settings
from django.urls import reverse
from django.contrib import messages

# Twilio imports
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from callManager.views import log_sms
import logging

# Create a logger instance
logger = logging.getLogger('callManager')
@login_required
def steward_invite(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    if request.method == "POST":
        worker_id = request.POST.get('worker_id')
        if worker_id:
            worker = get_object_or_404(Worker, id=worker_id, company=company)
            invitation = StewardInvitation.objects.create(worker=worker, company=company)
            registration_url = request.build_absolute_uri(reverse('register_steward', args=[str(invitation.token)]))
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
            message_body = f'You are invited to become a steward for {company.name}. Register: {registration_url}'
            if settings.TWILIO_ENABLED == 'enabled' and client:
                try:
                    client.messages.create(
                        body=message_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=worker.phone_number)
                    log_sms(company)
                    messages.success(request, f"Invitation sent to {worker.name}.")
                except TwilioRestException as e:
                    messages.error(request, f"Failed to send invitation: {str(e)}")
            else:
                log_sms(company)
                print(message_body)
                messages.success(request, f"Invitation printed for {worker.name}.")
            return redirect('manager_dashboard')
        else:
            messages.error(request, "Please select a worker.")
    workers = Worker.objects.filter(company=company).order_by('name')
    context = {
        'workers': workers,
        'search_query': '',
        'company': company}
    return render(request, 'callManager/steward_invite.html', context)

@login_required
def steward_invite_search(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    search_query = request.GET.get('search', '').strip()
    workers = Worker.objects.filter(company=company).order_by('name')
    if search_query:
        workers = workers.filter(Q(name__icontains=search_query) | Q(phone_number__icontains=search_query))
    context = {
        'workers': workers,
        'search_query': search_query}
    return render(request, 'callManager/steward_invite_partial.html', context)

