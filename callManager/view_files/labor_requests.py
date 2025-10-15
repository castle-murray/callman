
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
def labor_request_list(request, slug):
    if hasattr(request.user, 'administrator'):
        labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
        manager = labor_requirement.call_time.event.company.managers.first()
    elif not hasattr(request.user, 'manager'):
        return redirect('login')
    else:
        manager = request.user.manager
        labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    event = labor_requirement.call_time.event
    company = event.company
    workers = Worker.objects.filter(company=company).distinct()
    if request.method == "POST":
        if 'action' in request.POST and request.POST['action'] == 'add_worker':
            add_worker_form = WorkerFormLite(request.POST)
            if add_worker_form.is_valid():
                if add_worker_form.clean_phone_number in workers.values_list('phone_number', flat=True):
                    messages.error(request, "Worker with this phone number already exists.")
                worker = add_worker_form.save(commit=False)
                worker.company = company
                worker.save()
                messages.success(request, "Worker added successfully.")
                labor_request, created = LaborRequest.objects.get_or_create(
                    worker=worker,
                    labor_requirement=labor_requirement,
                    defaults={
                        'requested': True,
                        'sms_sent': False,
                        'is_reserved': False,
                        'token_short': generate_short_token()
                    }
                )
                if labor_requirement.labor_type not in worker.labor_types.all():
                    worker.labor_types.add(labor_requirement.labor_type)
                if not created and not labor_request.sms_sent:
                    labor_request.requested = True
                    labor_request.is_reserved = is_reserved
                    labor_request.token_short = generate_short_token()
                    labor_request.save()
                messages.success(request, f"{worker.name} queued for request.")
            
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
        if 'request_id' in request.POST:
            request_id = request.POST.get('request_id')
            action = request.POST.get('action')
            if request_id and action in ['confirm', 'decline', 'delete', 'call_filled']:
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement=labor_requirement)
                worker = labor_request.worker
                call_time = labor_request.labor_requirement.call_time
                if action == 'call_filled':
                    if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                        message_body = (
                                f"Sorry, the call has been filled:\n"
                                f"{event.event_name} @ {event.location_profile.name} - {labor_requirement.labor_type.name} - {call_time.date.strftime('%B %d')} at {labor_requirement.call_time.time.strftime('%I %p')}."
                        )
                        if settings.TWILIO_ENABLED == 'enabled' and client:
                            try:
                                client.messages.create(
                                    body=message_body,
                                    from_=settings.TWILIO_PHONE_NUMBER,
                                    to=str(worker.phone_number))
                            except TwilioRestException as e:
                                sms_errors.append(f"Failed to notify {worker.name}: {str(e)}")
                            finally:
                                log_sms(company)
                        else:
                            log_sms(company)
                            print(message_body)
                    labor_request.delete()
                    messages.success(request, f"Call filled for {worker.name}.")
                if action == 'confirm':
                    if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                        if labor_request.sms_sent:
                            message_body = (
                                    f"confirmed {labor_request.labor_requirement.labor_type}"
                                    f" for {event.event_name} - {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d')}"
                            )
                        else:
                            token = labor_request.token_short
                            confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                            message_body = (
                                    f"confirmed {labor_request.labor_requirement.labor_type}\n"
                                    f"for {event.event_name} - {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d')}\n"
                                    f"Details: {confirmation_url}"
                            )
                        msglen = len(message_body)
                        if settings.TWILIO_ENABLED == 'enabled' and client:
                            try:
                                client.messages.create(
                                    body=message_body,
                                    from_=settings.TWILIO_PHONE_NUMBER,
                                    to=str(worker.phone_number))
                            except TwilioRestException as e:
                                sms_errors.append(f"Failed to notify {worker.name}: {str(e)}")
                            finally:
                                log_sms(company)
                        else:
                            charges = 1
                            while msglen > 144:
                                charges += 1
                                msglen -= 144
                            log_sms(company)
                            print(message_body)
                            print(charges, msglen)
                    if labor_request.availability_response in [None, 'no']:  # Allow confirm from pending or declined
                        labor_request.availability_response = 'yes'
                        labor_request.responded_at = timezone.now()
                        confirmed_count = LaborRequest.objects.filter(
                            labor_requirement=labor_requirement,
                            confirmed=True
                        ).count()
                        if confirmed_count < labor_requirement.needed_labor:
                            labor_request.confirmed = True
                        labor_request.save()
                        messages.success(request, f"{worker.name} confirmed for {labor_requirement.labor_type.name}.")
                    elif labor_request.availability_response == 'yes' and not labor_request.confirmed:
                        confirmed_count = LaborRequest.objects.filter(
                            labor_requirement=labor_requirement,
                            confirmed=True
                        ).count()
                        if confirmed_count < labor_requirement.needed_labor:
                            labor_request.confirmed = True
                            labor_request.save()
                            messages.success(request, f"{worker.name} confirmed for {labor_requirement.labor_type.name}.")
                        else:
                            messages.error(request, "Labor requirement already filled.")
                elif action == 'decline':
                    if labor_request.availability_response is None:
                        labor_request.availability_response = 'no'
                        labor_request.responded_at = timezone.now()
                        if labor_request.is_reserved:
                            labor_request.is_reserved = False
                            confirmed_count = LaborRequest.objects.filter(
                                labor_requirement=labor_requirement,
                                confirmed=True
                            ).count()
                            if confirmed_count < labor_requirement.fcfs_positions:
                                available_fcfs = LaborRequest.objects.filter(
                                    labor_requirement=labor_requirement,
                                    availability_response='yes',
                                    confirmed=False,
                                    is_reserved=False
                                ).exclude(id=labor_request.id).order_by('responded_at').first()
                                if available_fcfs:
                                    available_fcfs.confirmed = True
                                    available_fcfs.save()
                    elif labor_request.availability_response == 'yes':
                        labor_request.confirmed = False
                        labor_request.availability_response = 'no'
                    labor_request.save()
                    messages.success(request, f"{worker.name} declined for {labor_requirement.labor_type.name}.")
                elif action == 'delete':
                    labor_request.delete()
                    messages.success(request, "Request deleted successfully.")
        elif 'worker_id' in request.POST:
            worker_id = request.POST.get('worker_id')
            action = request.POST.get('action')
            if worker_id and action in ['request', 'reserve']:
                worker = Worker.objects.get(id=worker_id)
                is_reserved = action == 'reserve'
                labor_request, created = LaborRequest.objects.get_or_create(
                    worker=worker,
                    labor_requirement=labor_requirement,
                    defaults={
                        'requested': True,
                        'sms_sent': False,
                        'is_reserved': is_reserved,
                        'token_short': generate_short_token(),
                    }
                )
                if labor_requirement.labor_type not in worker.labor_types.all():
                    worker.labor_types.add(labor_requirement.labor_type)
                if not created and not labor_request.sms_sent:
                    labor_request.requested = True
                    labor_request.is_reserved = is_reserved
                    labor_request.token_short = generate_short_token()
                    labor_request.save()
                messages.success(request, f"{worker.name} queued for request.")
        elif 'fcfs_positions' in request.POST:
            try:
                fcfs_positions = int(request.POST.get('fcfs_positions', 0))
                if 0 <= fcfs_positions <= labor_requirement.needed_labor:
                    labor_requirement.fcfs_positions = fcfs_positions
                    labor_requirement.save()
                    messages.success(request, f"FCFS positions updated to {fcfs_positions}.")
                else:
                    messages.error(request, "FCFS positions must be between 0 and needed labor.")
            except ValueError:
                messages.error(request, "Invalid FCFS positions value.")
        pending_requests = labor_requests.filter(availability_response__isnull=True)
        available_requests = labor_requests.filter(availability_response='yes', confirmed=False)
        confirmed_requests = labor_requests.filter(confirmed=True)
        declined_requests = labor_requests.filter(availability_response='no')
        workers = Worker.objects.filter(company=company).distinct()
        workers_list = list(workers)
        workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
        search_query = request.POST.get('search', request.GET.get('search', '')).strip()
        if search_query:
            workers_list = [w for w in workers_list if search_query.lower() in (w.name or '').lower() or search_query in (w.phone_number or '')]
        per_page = int(request.POST.get('per_page', request.GET.get('per_page', manager.per_page_preference)))
        paginator = Paginator(workers_list, per_page)
        page_number = request.POST.get('page', request.GET.get('page', 1))
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)
        conflicting_requests = LaborRequest.objects.filter(
            worker__in=page_obj.object_list,
            requested=True
        ).filter(
            labor_requirement__call_time__date__gte=labor_requirement.call_time.event.start_date,
            labor_requirement__call_time__date__lte=(labor_requirement.call_time.event.end_date or labor_requirement.call_time.event.start_date)
        ).filter(
            labor_requirement__call_time__time__gte=(datetime.combine(labor_requirement.call_time.date, labor_requirement.call_time.time) - timedelta(hours=5)).time(),
            labor_requirement__call_time__time__lte=(datetime.combine(labor_requirement.call_time.date, labor_requirement.call_time.time) + timedelta(hours=5)).time()
        ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
        worker_conflicts = {}
        for labor_request in conflicting_requests:
            if labor_request.worker_id not in worker_conflicts:
                worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
            conflict_info = {
                'event': labor_request.labor_requirement.call_time.event.event_name,
                'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
                'labor_type': labor_request.labor_requirement.labor_type.name,
                'status': 'Confirmed' if labor_request.confirmed else 'Available' if labor_request.availability_response == 'yes' else 'Declined' if labor_request.availability_response == 'no' else 'Pending',
                'call_time_id': labor_request.labor_requirement.call_time.id,
                'labor_type_id': labor_request.labor_requirement.labor_type.id
            }
            worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
            if labor_request.confirmed:
                worker_conflicts[labor_request.worker_id]['is_confirmed'] = True
        requested_worker_ids = list(labor_requests.values_list('worker__id', flat=True))
        context = {
            'labor_requirement': labor_requirement,
            'pending_requests': pending_requests,
            'pending_count': pending_requests.count(),
            'available_requests': available_requests,
            'available_count': available_requests.count(),
            'confirmed_requests': confirmed_requests,
            'confirmed_count': confirmed_requests.count(),
            'declined_requests': declined_requests,
            'declined_count': declined_requests.count(),
            'is_filled': labor_requirement.needed_labor <= confirmed_requests.count(),
            'workers': page_obj,
            'worker_conflicts': worker_conflicts,
            'requested_worker_ids': requested_worker_ids,
            'page_obj': page_obj,
            'search_query': search_query,
            'per_page': per_page
        }
        if request.headers.get('HX-Request') and 'worker_id' in request.POST:
            return render(request, 'callManager/labor_request_content_partial.html', context)
        if not request.headers.get('HX-Request'):
            return redirect('labor_request_list', slug=slug)
        return render(request, 'callManager/labor_request_list.html', context)
    pending_requests = labor_requests.filter(availability_response__isnull=True)
    available_requests = labor_requests.filter(availability_response='yes', confirmed=False)
    confirmed_requests = labor_requests.filter(confirmed=True)
    declined_requests = labor_requests.filter(availability_response='no')
    workers = Worker.objects.filter(company=company).distinct()
    workers_list = list(workers)
    workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers_list = [w for w in workers_list if search_query.lower() in (w.name or '').lower() or search_query in (w.phone_number or '')]
    per_page = manager.per_page_preference
    paginator = Paginator(workers_list, per_page)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    conflicting_requests = LaborRequest.objects.filter(
        worker__in=page_obj.object_list,
        requested=True
    ).filter(
        labor_requirement__call_time__date__gte=labor_requirement.call_time.event.start_date,
        labor_requirement__call_time__date__lte=(labor_requirement.call_time.event.end_date or labor_requirement.call_time.event.start_date)
    ).filter(
        labor_requirement__call_time__time__gte=(datetime.combine(labor_requirement.call_time.date, labor_requirement.call_time.time) - timedelta(hours=5)).time(),
        labor_requirement__call_time__time__lte=(datetime.combine(labor_requirement.call_time.date, labor_requirement.call_time.time) + timedelta(hours=5)).time()
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    worker_conflicts = {}
    for labor_request in conflicting_requests:
        if labor_request.worker_id not in worker_conflicts:
            worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.confirmed else 'Available' if labor_request.availability_response == 'yes' else 'Declined' if labor_request.availability_response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id
        }
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.confirmed:
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True
    labor_types = LaborType.objects.filter(company=manager.company)
    requested_worker_ids = list(labor_requests.values_list('worker__id', flat=True))
    context = {
        'labor_requirement': labor_requirement,
        'pending_requests': pending_requests,
        'pending_count': pending_requests.count(),
        'available_requests': available_requests,
        'available_count': available_requests.count(),
        'confirmed_requests': confirmed_requests,
        'confirmed_count': confirmed_requests.count(),
        'declined_requests': declined_requests,
        'declined_count': declined_requests.count(),
        'is_filled': labor_requirement.needed_labor <= confirmed_requests.count(),
        'workers': page_obj,
        'worker_conflicts': worker_conflicts,
        'requested_worker_ids': requested_worker_ids,
        'page_obj': page_obj,
        'labor_types': labor_types,
        'search_query': search_query,
        'per_page': per_page
    }
    return render(request, 'callManager/labor_request_list.html', context)

@login_required
def fill_labor_request_list(request, slug):
    if hasattr(request.user, 'administrator'):
        labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
        manager = labor_requirement.call_time.event.company.managers.first()
    elif not hasattr(request.user, 'manager'):
        return redirect('login')
    else:
        manager = request.user.manager
        labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    workers = Worker.objects.filter(company=manager.company).distinct()
    search_query = request.GET.get('search', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    if search_query or skill_id:
        query = Q()
        if search_query:
            query &= Q(name__icontains=search_query) | Q(phone_number__icontains=search_query)
        if skill_id:
            query &= Q(labor_types__id=skill_id)
        workers = workers.filter(query)
    workers_list = list(workers)
    workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
    if request.GET.get('per_page'):
        per_page = int(request.GET.get('per_page'))
        manager.per_page_preference = per_page
        manager.save()
    else:
        per_page = manager.per_page_preference
    paginator = Paginator(workers_list, per_page)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    current_call_time = labor_requirement.call_time
    event_start_date = current_call_time.event.start_date
    event_end_date = current_call_time.event.end_date or event_start_date
    call_datetime = datetime.combine(event_start_date, current_call_time.time)
    window_start = call_datetime - timedelta(hours=5)
    window_end = call_datetime + timedelta(hours=5)
    conflicting_requests = LaborRequest.objects.filter(
        worker__in=page_obj.object_list,
        requested=True).filter(
        labor_requirement__call_time__date__gte=window_start.date(),
        labor_requirement__call_time__date__lte=window_end.date()).filter(
        labor_requirement__call_time__time__gte=window_start.time() if window_start.date() == labor_requirement.call_time.date else '00:00:00',
        labor_requirement__call_time__time__lte=window_end.time() if window_end.date() == labor_requirement.call_time.date else '23:59:59').select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    worker_conflicts = {}
    for labor_request in conflicting_requests:
        if labor_request.worker_id not in worker_conflicts:
            worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.confirmed else 'Available' if labor_request.availability_response == 'yes' else 'Declined' if labor_request.availability_response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id}
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.confirmed:
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True
    requested_worker_ids = list(labor_requests.values_list('worker__id', flat=True))
    pending_requests = labor_requests.filter(availability_response__isnull=True)
    available_requests = labor_requests.filter(availability_response='yes', confirmed=False)
    confirmed_requests = labor_requests.filter(confirmed=True)
    labor_types = LaborType.objects.filter(company=manager.company)
    context = {
        'labor_requirement': labor_requirement,
        'pending_count': pending_requests.count(),
        'available_count': available_requests.count(),
        'confirmed_count': confirmed_requests.count(),
        'workers': page_obj,
        'worker_conflicts': worker_conflicts,
        'requested_worker_ids': requested_worker_ids,
        'page_obj': page_obj,
        'search_query': search_query,
        'skill_id': skill_id,
        'per_page': per_page,
        'labor_types': labor_types}
    return render(request, 'callManager/fill_labor_request_list_partial.html', context)

@login_required
def worker_fill_partial(request, slug, worker_id):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    worker = get_object_or_404(Worker, id=worker_id)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    requested_worker_ids = list(labor_requests.values_list('worker__id', flat=True))
    
    # Conflict data (copied from fill_labor_request_list)
    current_call_time = labor_requirement.call_time
    event_start_date = current_call_time.event.start_date
    event_end_date = current_call_time.event.end_date or event_start_date
    call_datetime = datetime.combine(event_start_date, current_call_time.time)
    window_start = call_datetime - timedelta(hours=5)
    window_end = call_datetime + timedelta(hours=5)
    conflicting_requests = LaborRequest.objects.filter(
        worker=worker,
        requested=True
    ).filter(
        labor_requirement__call_time__date__gte=window_start.date(),
        labor_requirement__call_time__date__lte=window_end.date()
    ).filter(
        labor_requirement__call_time__time__gte=window_start.time() if window_start.date() == labor_requirement.call_time.date else '00:00:00',
        labor_requirement__call_time__time__lte=window_end.time() if window_end.date() == labor_requirement.call_time.date else '23:59:59'
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    worker_conflicts = {}
    worker_data = {'conflicts': [], 'is_confirmed': False}
    for labor_request in conflicting_requests:
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.confirmed else 'Available' if labor_request.availability_response == 'yes' else 'Declined' if labor_request.availability_response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id
        }
        worker_data['conflicts'].append(conflict_info)
        if labor_request.confirmed:
            worker_data['is_confirmed'] = True
    worker_conflicts[worker.id] = worker_data
    context = {
        'labor_requirement': labor_requirement,
        'worker': worker,
        'worker_data': worker_data,
        'worker_conflicts': worker_conflicts,
        'requested_worker_ids': requested_worker_ids
    }
    return render(request, 'callManager/worker_fill_partial.html', context)

@login_required
def declined_requests(request):
    if request.method == "POST":
        #delete request button
        if 'delete_request' in request.POST:
            request_id = request.POST.get('request_id')
            request = get_object_or_404(LaborRequest, id=request_id)
            request.delete()
            return redirect('declined_requests')
    manager = request.user.manager
    company = manager.company
    declined_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        availability_response='no',
    ).select_related('worker', 'labor_requirement__call_time__event')
    context = {
        'requests': declined_requests,
    }
    return render(request, 'callManager/declined_requests.html', context)

@login_required
def pending_requests(request):
    if request.method == "POST":
        #delete request button
        if 'delete_request' in request.POST:
            request_id = request.POST.get('request_id')
            request = get_object_or_404(LaborRequest, id=request_id)
            request.delete()
            return redirect('pending_requests')
        elif 'confirm_request' in request.POST:
            request_id = request.POST.get('request_id')
            labor_request = get_object_or_404(LaborRequest, id=request_id)
            labor_request.availability_response = 'yes'
            labor_request.confirmed = True
            labor_request.save()
            return redirect('pending_requests')
    manager = request.user.manager
    company = manager.company
    pending_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        availability_response__isnull=True,
    ).select_related('worker', 'labor_requirement__call_time__event')
    context = {
        'requests': pending_requests,
    }
    return render(request, 'callManager/pending_requests.html', context)

@login_required
def edit_labor_requirement(request, slug):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    if request.method == "POST":
        form = LaborRequirementForm(request.POST, instance=labor_requirement, company=manager.company)
        if form.is_valid():
            form.save()
            return redirect('event_detail', slug=labor_requirement.call_time.event.slug)
    else:
        form = LaborRequirementForm(instance=labor_requirement, company=manager.company)
    context = {'form': form, 'labor_requirement': labor_requirement}
    return render(request, 'callManager/edit_labor_requirement.html', context)

@login_required
def delete_labor_requirement(request, slug):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    if request.method == "POST":
        labor_requirement.delete()
        return redirect('event_detail', slug=labor_requirement.call_time.event.slug)
    return redirect('event_detail', slug=labor_requirement.call_time.event.slug)  # Fallback for GET

@login_required
def labor_request_action(request, request_id, action):
    if not request.user.workers.exists():
        return redirect('login')
    labor_request = get_object_or_404(LaborRequest, id=request_id, worker__user=request.user)
    if request.method == "POST":
        if labor_request.availability_response is not None or labor_request.confirmed:
            messages.error(request, "This request cannot be modified.")
            return redirect('user_profile')
        if action == 'confirm':
            if labor_request.is_reserved or labor_request.labor_requirement.fcfs_positions > 0:
                labor_request.confirmed = True
            labor_request.availability_response = 'yes'
            labor_request.save()
            messages.success(request, "Request confirmed successfully.")
        elif action == 'decline':
            if labor_request.is_reserved:
                labor_request.is_reserved = False
                if labor_request.labor_requirement.fcfs_positions > 0:
                    labor_request.labor_requirement.fcfs_positions += 1
                    labor_request.labor_requirement.save()
            labor_request.availability_response = 'no'
            labor_request.save()
            messages.success(request, "Request declined successfully.")
        else:
            messages.error(request, "Invalid action.")
        return redirect('user_profile')
    messages.error(request, "Invalid request method.")
    return redirect('user_profile')

