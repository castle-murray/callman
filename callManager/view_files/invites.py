
#models
from time import sleep
from callManager.models import (
        CallTime,
        LaborRequest,
        Event,
        LaborRequirement,
        LaborType,
        OneTimeLoginToken,
        PasswordResetToken,
        Steward,
        TimeChangeConfirmation,
        Worker,
        TimeEntry,
        MealBreak,
        SentSMS,
        ClockInToken,
        Owner,
        OwnerInvitation,
        Manager,
        ManagerInvitation,
        Company,
        StewardInvitation,
        TemporaryScanner,
        LocationProfile,
        )
#forms
from callManager.forms import (
        CallTimeForm,
        CompanyHoursForm,
        LaborTypeForm,
        LaborRequirementForm,
        EventForm,
        WorkerForm,
        WorkerFormLite,
        WorkerImportForm,
        WorkerRegistrationForm,
        SkillForm,
        OwnerRegistrationForm,
        ManagerRegistrationForm,
        CompanyForm,
        LocationProfileForm,
        AddWorkerForm
        )
# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.http import base64
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, time, timedelta
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.contrib.messages import get_messages as django_get_messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import FileResponse
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from django.contrib.auth.views import LoginView
from callManager.utils import send_custom_email

# Twilio imports
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from twilio.twiml.messaging_response import MessagingResponse

# repotlab imports for PDF generation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import PageBreak, Table, TableStyle, Paragraph, SimpleDocTemplate, Table, TableStyle, Spacer, KeepTogether
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet

# other imports
import qrcode
from io import BytesIO, TextIOWrapper
import re
import random
import string
import uuid
from urllib.parse import urlencode, quote
from user_agents import parse

# posssibly imports
import pytz
import io

from callManager.views import log_sms, send_message
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

