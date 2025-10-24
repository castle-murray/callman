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

from callManager.views import log_sms, send_message, generate_short_token
import logging

# Create a logger instance
logger = logging.getLogger('callManager')


@login_required
def event_detail(request, slug):
    """Event detail page for managers and administrators"""
    event = get_object_or_404(Event, slug=slug)
    company = event.company
    user = request.user
    if not hasattr(user, 'administrator') and not hasattr(user, 'manager'):
        return redirect('login')
    elif not hasattr(user, 'administrator') and hasattr(user, 'manager'):
        if user.manager.company != company:
            return redirect('login')
        else:
            manager = user.manager
    elif hasattr(user, 'administrator'):
        if hasattr(user, 'manager') and user.manager.company == company:
            manager = user.manager
        else:
            manager = company.managers.first()  # Get first manager or None
    else:
        return redirect('login')
   
    call_times = event.call_times.all().order_by('date', 'time')
    for call_time in call_times:
        if call_time.original_time != call_time.time or call_time.original_date != call_time.date:
            call_time.has_changed = True
        else:
            call_time.has_changed = False
    labor_requirements = LaborRequirement.objects.filter(call_time__event=event)
    labor_requests = LaborRequest.objects.filter(labor_requirement__call_time__event=event).values('labor_requirement_id').annotate(
        pending_count=Count('id', filter=Q(requested=True) & Q(availability_response__isnull=True)),
        confirmed_count=Count('id', filter=Q(confirmed=True)),
        rejected_count=Count('id', filter=Q(availability_response='no'))
    )
    labor_counts = {}
    for lr in labor_requirements:
        lr_id = lr.id
        pending = next((item['pending_count'] for item in labor_requests if item['labor_requirement_id'] == lr_id), 0)
        confirmed = next((item['confirmed_count'] for item in labor_requests if item['labor_requirement_id'] == lr_id), 0)
        rejected = next((item['rejected_count'] for item in labor_requests if item['labor_requirement_id'] == lr_id), 0)
        needed = lr.needed_labor
        non_rejected = pending + confirmed
        if non_rejected > needed:
            overbooked = non_rejected - needed
            if confirmed >= needed:
                display_text = f"{confirmed} filled"
                if overbooked > 0:
                    display_text += f", overbooked by {overbooked}"
            else:
                display_text = f"{needed} needed, overbooked by {overbooked} pending"
        elif confirmed >= needed:
            display_text = f"{confirmed} filled"
        else:
            display_text = f"{needed} needed ({pending} pending, {confirmed} confirmed, {rejected} rejected)"
        labor_counts[lr_id] = {
            'pending': pending,
            'confirmed': confirmed,
            'rejected': rejected,
            'display_text': display_text,
            'labor_requirement': lr
        }
    if request.method == "POST" and 'send_messages' in request.POST:
        if not hasattr(user, 'administrator') and event.company != manager.company:
            messages.error(request, "You do not have permission to send messages for this event.")
            return redirect('event_detail', slug=slug)
        queued_requests = LaborRequest.objects.filter(
                labor_requirement__call_time__event=event,
                requested=True,
                sms_sent=False).select_related('worker')
        if queued_requests.exists():
            sms_errors = []
            workers_to_notify = {}
            for labor_request in queued_requests:
                worker = labor_request.worker
                if worker.id not in workers_to_notify:
                    workers_to_notify[worker.id] = {'worker': worker, 'requests': []}
                workers_to_notify[worker.id]['requests'].append(labor_request)
            for _, data in workers_to_notify.items():
                worker = data['worker']
                requests = data['requests']
                # Use existing token_short if available, otherwise generate new
                token = next((req.token_short for req in requests if req.token_short), generate_short_token())
                confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                if event.is_single_day:
                    message_body = f"This is {manager.user.first_name}/{company.name_short or company.name}: Confirm availability for {event.event_name} on {event.start_date}: {confirmation_url}"
                else:
                    message_body = f"This is {manager.user.first_name}/{company.name_short or company.name}: Confirm availability for {event.event_name}: {confirmation_url}"
                if len(message_body) > 144:
                    message_body = message_body[:141] + "..."
                sms_errors.extend(send_message(message_body, worker, manager, company))
                for labor_request in requests:
                    if worker.sms_consent == True:
                        labor_request.sms_sent = True
                    labor_request.token_short = token
                    labor_request.save()
            message = f"Messages processed for {len(workers_to_notify)} workers."
            if sms_errors:
                message += f" Errors: {', '.join(sms_errors)}."
        else:
            message = "No queued requests to send."
        context = {
            'company': company,
            'event': event,
            'call_times': call_times,
            'labor_counts': labor_counts,
            'message': message
        }
        return render(request, 'callManager/event_detail.html', context)
    context = {
        'company': company,
        'event': event,
        'call_times': call_times,
        'labor_counts': labor_counts
    }
    return render(request, 'callManager/event_detail.html', context)


@login_required
def edit_event(request, slug):
    event = get_object_or_404(Event, slug=slug)
    company = event.company
    user = request.user
    if not hasattr(user, 'administrator') and not hasattr(user, 'manager'):
        return redirect('login')
    elif not hasattr(user, 'administrator') and hasattr(user, 'manager'):
        if user.manager.company != company:
            return redirect('login')
        else:
            manager = user.manager
    elif hasattr(user, 'administrator'):
        if hasattr(user, 'manager') and user.manager.company == company:
            manager = user.manager
        else:
            manager = company.managers.first()  # Get first manager or None
    else:
        return redirect('login')
    if request.method == "POST":
        form = EventForm(request.POST, instance=event, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, f"Event '{event.event_name}' updated successfully.")
            return redirect('manager_dashboard')
    else:
        form = EventForm(instance=event, company=company)
    context = {
        'company': company,
        'form': form,
        'event': event,
    }
    return render(request, 'callManager/edit_event.html', context)

@login_required
def delete_event(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    if request.method == "POST":
        event.delete()
        return redirect('manager_dashboard')
    return redirect('manager_dashboard')  # Fallback for GET requests

@login_required
def admin_search_events(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('login')
    admindashboard = True
    yesterday = timezone.now().date() - timedelta(days=1)
    search_query = request.GET.get('search', '').strip().lower()
    include_past = request.GET.get('include_past', '') == 'on'
    events = Event.objects.all()
    if not include_past:
        events = events.filter(Q(start_date__gte=yesterday) | Q(end_date__gte=yesterday))
    if search_query:
        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
            'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12}
        terms = search_query.split()
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
    labor_requirements = LaborRequirement.objects.select_related(
        'labor_type', 'call_time__event').annotate(
        confirmed_count=Count('labor_requests', filter=Q(labor_requests__confirmed=True)))
    event_labor_needs = {}
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
        'events': events,
        'event_labor_needs': event_labor_needs,
        'search_query': search_query,
        'include_past': include_past,
        'admindashboard': admindashboard,
        }
    return render(request, 'callManager/events_list_partial.html', context)


@login_required
def cancel_event(request, slug):
    event = get_object_or_404(Event, slug=slug)
    if request.method == "POST":
        call_times = event.call_times.all()
        message_body = f"Sorry, the event has been canceled: {event.event_name} on {event.start_date}"
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
        for call_time in call_times:
            labor_requirements = call_time.labor_requirements.all()
            for labor_requirement in labor_requirements:
                labor_requests = labor_requirement.labor_requests.all()
                for labor_request in labor_requests:
                    if labor_request.worker.sms_consent and not labor_request.worker.stop_sms and labor_request.worker.phone_number:
                        if labor_request.confirmed or labor_request.availability_response == 'yes' or labor_request.availability_response == None:
                            if settings.TWILIO_ENABLED == 'enabled' and client:
                                try:
                                    client.messages.create(
                                        body=message_body,
                                        from_=settings.TWILIO_PHONE_NUMBER,
                                        to=str(labor_request.worker.phone_number))
                                except TwilioRestException as e:
                                    print(f"Failed to notify {labor_request.worker.name}: {str(e)}")
                                finally:
                                    log_sms(event.company)
                            else:
                                log_sms(event.company)
                                print(message_body)
        event.canceled = True
        event.steward = None
        event.save()
    manager = request.user.manager
    company = manager.company
    yesterday = timezone.now().date() - timedelta(days=1)
    search_query = request.GET.get('search', '').strip().lower()
    include_past = request.GET.get('include_past', '') == 'on'
    events = Event.objects.filter(company=company)
    if not include_past:
        events = events.filter(Q(start_date__gte=yesterday) | Q(end_date__gte=yesterday))
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
        'include_past': include_past}
                    
    return render(request, 'callManager/events_list_partial.html', context)

@login_required
def add_call_time(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    if request.method == "POST":
        form = CallTimeForm(request.POST, event=event)
        if form.is_valid():
            call_time = form.save(commit=False)
            call_time.event = event
            call_time.save()
            return redirect('event_detail', slug=event.slug)
    else:
        form = CallTimeForm(event=event)
    return render(request, 'callManager/add_call_time.html', {'form': form, 'event': event})


@login_required
def assign_steward(request, slug):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    event = get_object_or_404(Event, slug=slug, company=request.user.manager.company)
    if request.method == "POST":
        steward_id = request.POST.get('steward_id')
        if steward_id:
            steward = get_object_or_404(Steward, id=steward_id, company=request.user.manager.company)
            event.steward = steward
        else:
            event.steward = None
        event.save()
    return redirect('manager_dashboard')

@login_required
def generate_signin_qr(request, slug):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    event = get_object_or_404(Event, slug=slug, company=request.user.manager.company)
    if request.method == "POST":
        temp_username = f"scanner_{uuid.uuid4().hex[:8]}"
        temp_password = uuid.uuid4().hex[:12]
        temp_user = User.objects.create_user(
            username=temp_username,
            password=temp_password)
        scanner = TemporaryScanner.objects.create(
            event=event,
            user=temp_user,
            expires_at=timezone.now() + timedelta(hours=24))
        qr_url = request.build_absolute_uri(reverse('signin_station', args=[str(scanner.token)]))
        context = {'qr_url': qr_url, 'event': event}
        return render(request, 'callManager/signin_qr.html', context)
    return render(request, 'callManager/signin_qr.html', {'event': event})

@login_required
def search_events(request):
    manager = request.user.manager
    company = manager.company
    yesterday = timezone.now().date() - timedelta(days=1)
    search_query = request.GET.get('search', '').strip().lower()
    include_past = request.GET.get('include_past', '') == 'on'
    events = Event.objects.filter(company=company)
    if not include_past:
        events = events.filter(Q(start_date__gte=yesterday) | Q(end_date__gte=yesterday))
    if search_query:
        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
            'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12}
        terms = search_query.split()
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
    labor_requirements = LaborRequirement.objects.filter(
        call_time__event__company=company).select_related(
        'labor_type', 'call_time__event').annotate(
        confirmed_count=Count('labor_requests', filter=Q(labor_requests__confirmed=True)))
    stewards = Steward.objects.filter(company=company)
    event_labor_needs = {}
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
        'events': events,
        'event_labor_needs': event_labor_needs,
        'search_query': search_query,
        'include_past': include_past,
        'stewards': stewards}
    return render(request, 'callManager/events_list_partial.html', context)


@login_required
def create_event(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    print(f"Company: {company.name}, Location Profiles: {company.location_profiles.count()}")
    if request.method == "POST":
        form = EventForm(request.POST, company=company)
        if form.is_valid():
            event = form.save(commit=False)
            event.company = company
            event.save()
            return redirect('event_detail', slug=event.slug)
    else:
        form = EventForm(company=company)
    context = {'form': form, 'company': company}
    return render(request, 'callManager/create_event.html', context)

