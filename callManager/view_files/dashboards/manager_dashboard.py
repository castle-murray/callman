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

import logging


# Create a logger instance
logger = logging.getLogger('callManager')

@login_required
def manager_dashboard(request):
    if not hasattr(request.user, 'manager') and hasattr(request.user, 'steward'):
        return redirect('steward_dashboard')
    elif not hasattr(request.user, 'manager') and not hasattr(request.user, 'steward'):
        return redirect('login')
    manager = request.user.manager
    has_skills = LaborType.objects.filter(company=manager.company).exists()
    has_locations = LocationProfile.objects.filter(company=manager.company).exists()
    has_workers = Worker.objects.filter(company=manager.company).exists()
    company = manager.company
    yesterday = timezone.now().date() - timedelta(days=1)
    search_query = request.GET.get('search', '').strip().lower()
    include_past = request.GET.get('include_past', '') == 'on'
    events = Event.objects.filter(company=company)
    if not include_past:
        events = events.filter(Q(start_date__gte=yesterday) | Q(end_date__gte=yesterday))
    if search_query:
        terms = search_query.split()
        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
            'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12}
        for term in terms:
            term_filter = Q()
            if term in month_map:
                term_filter = Q(start_date__month=month_map[term])
            elif term.isdigit() and len(term) == 4:
                term_filter = Q(start_date__year=int(term))
            elif re.match(r'\d{4}-\d{2}-\d{2}', term):
                try:
                    search_date = datetime.strptime(term, '%Y-%m-%d').date()
                    term_filter = Q(start_date__exact=search_date) | Q(end_date__exact=search_date)
                except ValueError:
                    pass
            else:
                term_filter = Q(event_name__icontains=term) | Q(location_profile__name__icontains=term)
            events = events.filter(term_filter)
    events = events.order_by('start_date').distinct()
    total_events = events.count()
    pending_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        availability_response__isnull=True).count()
    declined_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        availability_response='no').count()
    labor_requirements = LaborRequirement.objects.filter(
        call_time__event__company=company).select_related(
        'labor_type', 'call_time__event').annotate(
        confirmed_count=Count('labor_requests', filter=Q(labor_requests__confirmed=True)))
    unfilled_spots = sum(max(0, lr.needed_labor - lr.confirmed_count) for lr in labor_requirements)
    current_date = timezone.now()
    start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_of_month + timedelta(days=32)).replace(day=1)
    sent_messages = SentSMS.objects.filter(
        company=company,
        datetime_sent__gte=start_of_month,
        datetime_sent__lt=next_month).count()
    event_labor_needs = {}
    stewards = Steward.objects.filter(company=company)
    for event in events:
        event_requirements = [lr for lr in labor_requirements if lr.call_time.event_id == event.id]
        unfilled_requirements = [
            lr for lr in event_requirements if lr.confirmed_count < lr.needed_labor]
        unfilled_count = len(unfilled_requirements)
        total_unfilled_spots = sum(max(0, lr.needed_labor - lr.confirmed_count) for lr in unfilled_requirements)
        if unfilled_count > 3:
            labor_needs_text = f"{unfilled_count} unfilled, {total_unfilled_spots} total labor needed"
        elif unfilled_count > 0:
            labor_needs_text = ", ".join(
                f"{lr.labor_type.name}: {max(0, lr.needed_labor - lr.confirmed_count)} needed"
                for lr in unfilled_requirements)
        else:
            labor_needs_text = "All calls filled"
        event_labor_needs[event.id] = {
            'unfilled_count': unfilled_count,
            'total_unfilled_spots': total_unfilled_spots,
            'labor_needs_text': labor_needs_text}
    context = {
        'company': company,
        'events': events,
        'total_events': total_events,
        'pending_requests': pending_requests,
        'sent_messages': sent_messages,
        'declined': declined_requests,
        'unfilled_spots': unfilled_spots,
        'event_labor_needs': event_labor_needs,
        'search_query': search_query,
        'stewards': stewards,
        'has_skills': has_skills,
        'has_locations': has_locations,
        'has_workers': has_workers,
        'include_past': include_past}
    return render(request, 'callManager/manager_dashboard.html', context)
