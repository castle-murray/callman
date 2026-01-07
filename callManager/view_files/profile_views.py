#models
from django.utils import timezone
from callManager.models import LaborRequest

# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

import logging

# Create a logger instance
logger = logging.getLogger('callManager')

@login_required
def user_profile(request):
    workers = request.user.workers.all()
    if not workers.exists():
        messages.error(request, "You are not currently associated with any company accounts. Please contact your manager.")
        return redirect('login')
    labor_requests = LaborRequest.objects.filter(worker__user=request.user).select_related(
        'labor_requirement__call_time__event'
    ).order_by('labor_requirement__call_time__date')
    #requests from today forward
    confirmed = labor_requests.filter(confirmed=True)
    upcoming = labor_requests.filter(labor_requirement__call_time__date__gte=timezone.now().date(), sms_sent=True).order_by('labor_requirement__call_time__call_unixtime')
    past = confirmed.filter(labor_requirement__call_time__date__lt=timezone.now().date(), sms_sent=True)

    context = {
            'labor_requests': labor_requests, 
            'workers': workers,
            'upcoming': upcoming,
            'past': past
            }
    return render(request, 'callManager/user_profile.html', context)
