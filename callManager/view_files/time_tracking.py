
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
def call_time_tracking_meal_edit(request, slug):
    call_time = get_object_or_404(CallTime, slug=slug)
    meal_break_id = request.GET.get('meal_break_id')
    meal_break = get_object_or_404(MealBreak, id=meal_break_id)
    time_entry = meal_break.time_entry
    hours = range(24)
    minutes = ['00', '30']
    context = {
        'call_time': call_time,
        'time_entry': time_entry,
        'meal_break': meal_break,
        'hours': hours,
        'minutes': minutes
    }
    return render(request, 'callManager/meal_break_edit_partial.html', context)

@login_required
def call_time_tracking_meal_display(request, slug):
    call_time = get_object_or_404(CallTime, slug=slug)
    meal_break_id = request.GET.get('meal_break_id')
    meal_break = get_object_or_404(MealBreak, id=meal_break_id)
    context = {
        'call_time': call_time,
        'meal_break': meal_break
    }
    return render(request, 'callManager/meal_break_display_partial.html', context)

@login_required
def call_time_tracking_display(request, slug):
    call_time = get_object_or_404(CallTime, slug=slug)
    request_id = request.GET.get('request_id')
    field = request.GET.get('field')
    labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
    context = {
        'call_time': call_time,
        'labor_request': labor_request,
        'field': field
    }
    return render(request, 'callManager/time_entry_display_partial.html', context)

def display_qr_code(request, slug, worker_slug):
    event = get_object_or_404(Event, slug=slug)
    worker = get_object_or_404(Worker, slug=worker_slug)
    # if the event doesn't exist, return a 404
    if not event:
        raise Http404("Event not found")
    token, created = ClockInToken.objects.get_or_create(
        event=event,
        worker=worker,
        defaults={'expires_at': timezone.now() + timedelta(days=1), 'qr_sent': False})
    clock_in_url = request.build_absolute_uri(reverse('worker_clock_in_out', args=[str(token.token)]))
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(clock_in_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    context = {
        'event': event,
        'worker': worker,
        'clock_in_url': clock_in_url,
        'qr_code_data': base64.b64encode(buffer.getvalue()).decode('utf-8')}
    return render(request, 'callManager/display_qr_code.html', context)

@login_required
def manager_display_qr_code(request, slug, worker_slug):
    """QR code for managers to use to clock in workers."""
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    worker = get_object_or_404(Worker, slug=worker_slug)
    token, created = ClockInToken.objects.get_or_create(
        event=event,
        worker=worker,
        defaults={'expires_at': timezone.now() + timedelta(days=1)})
    clock_in_url = request.build_absolute_uri(reverse('worker_clock_in_out', args=[str(token.token)]))
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(clock_in_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    context = {
        'event': event,
        'worker': worker,
        'clock_in_url': clock_in_url,
        'qr_code_data': base64.b64encode(buffer.getvalue()).decode('utf-8')}
    return render(request, 'callManager/display_qr_code.html', context)

@login_required
def scan_qr_code(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    context = {'event': event}
    return render(request, 'callManager/scan_qr_code.html', context)

@login_required
def worker_clock_in_out(request, token):
    token_obj = get_object_or_404(ClockInToken, token=token)
    if token_obj.expires_at < timezone.now():
        return render(request, 'callManager/clock_in_error.html', {'message': 'This clock-in link has expired.'})
    event = token_obj.event
    worker = token_obj.worker
    company = event.company
    # Store referer in session on GET, use session referer for redirects
    if request.method == "GET":
        referer = request.META.get('HTTP_REFERER', reverse('scan_qr_code', kwargs={'slug': event.slug}))
        request.session['clock_in_referer'] = referer
        print(f"Stored Referer: {referer}")
    referer = request.session.get('clock_in_referer', reverse('scan_qr_code', kwargs={'slug': event.slug}))
    print(f"Using Referer: {referer}")
    if request.method == "POST":
        call_time_id = request.POST.get('call_time_id')
        action = request.POST.get('action')
        call_time = get_object_or_404(CallTime, id=call_time_id, event=event)
        labor_request = get_object_or_404(LaborRequest, worker=worker, labor_requirement__call_time=call_time, confirmed=True)
        minimum_hours = labor_request.labor_requirement.minimum_hours or call_time.minimum_hours or event.location_profile.minimum_hours or company.minimum_hours
        time_entry, created = TimeEntry.objects.get_or_create(
            labor_request=labor_request,
            worker=worker,
            call_time=call_time,
            defaults={'start_time': None, 'end_time': None})
        if action == 'clock_in' and not time_entry.start_time:
            time_entry.start_time = datetime.combine(call_time.date, call_time.time)
            time_entry.save()
            messages.success(request, f"Signed in at {time_entry.start_time.strftime('%I:%M %p')}.")
        elif action == 'clock_out' and time_entry.start_time and not time_entry.end_time:
            end_time = timezone.now()
            minutes = end_time.minute
            round_up = event.location_profile.hour_round_up or company.hour_round_up
            if minutes > 30 + round_up:
                end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            elif minutes > company.hour_round_up:
                end_time = end_time.replace(minute=30, second=0, microsecond=0)
            else:
                end_time = end_time.replace(minute=0, second=0, microsecond=0)
            if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
                end_time = time_entry.start_time + timedelta(hours=minimum_hours)
            time_entry.end_time = end_time
            time_entry.save()
            messages.success(request, f"Signed out at {time_entry.end_time.strftime('%I:%M %p')}.")
        else:
            messages.error(request, "Invalid action or time entry state.")
        return redirect(referer)
    now = timezone.now()
    one_hour_before = now - timedelta(hours=1)
    one_hour_after = now + timedelta(hours=1)
    call_times = CallTime.objects.filter(
        event=event,
        labor_requirements__labor_requests__worker=worker,
        labor_requirements__labor_requests__confirmed=True).filter(
        Q(date=now.date(), time__range=(one_hour_before.time(), one_hour_after.time())) |
        Q(timeentry__worker=worker, timeentry__start_time__isnull=False, timeentry__end_time__isnull=True)
    ).exclude(
        timeentry__worker=worker,
        timeentry__start_time__isnull=False,
        timeentry__end_time__isnull=False
    ).distinct()
    print(one_hour_before.time(), one_hour_after.time())
    call_time_status = []
    for call_time in call_times:
        is_signed_in = TimeEntry.objects.filter(
            worker=worker,
            call_time=call_time,
            start_time__isnull=False,
            end_time__isnull=True).exists()
        call_time_status.append({
            'call_time': call_time,
            'is_signed_in': is_signed_in})
    no_call_times_message = "No sign in available at this time. See steward." if not call_times.exists() else None
    context = {
        'event': event,
        'worker': worker,
        'call_time_status': call_time_status,
        'token': token,
        'no_call_times_message': no_call_times_message}
    return render(request, 'callManager/worker_clock_in_out.html', context)

def signin_station(request, token):
    scanner = get_object_or_404(TemporaryScanner, token=token, expires_at__gt=timezone.now())
    user = scanner.user
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return render(request, 'callManager/signin_scanner.html', {'event': scanner.event})

@login_required
def delete_meal_break(request, meal_break_id):
    meal_break = get_object_or_404(MealBreak, id=meal_break_id)
    meal_break.delete()
    if request.headers.get('HX-Request'):
        print("Deleted meal break")
    return HttpResponse("")

