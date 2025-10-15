
#models
from time import sleep
from callManager.models import (
        Event,
        )

# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required


import logging

# Create a logger instance
logger = logging.getLogger('callManager')

@login_required
def steward_dashboard(request):
    if not hasattr(request.user, 'steward'):
        return redirect('login')
    steward = request.user.steward
    events = Event.objects.filter(steward=steward).order_by('start_date')
    context = {'events': events}
    return render(request, 'callManager/steward_dashboard.html', context)

