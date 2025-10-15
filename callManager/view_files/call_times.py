
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
from callManager.views import log_sms, send_message
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
def add_labor_to_call(request, slug):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    if request.method == "POST":
        form = LaborRequirementForm(request.POST, company=manager.company, call_time=call_time)
        if form.is_valid():
            labor_requirement = form.save(commit=False)
            labor_requirement.call_time = call_time
            existing = LaborRequirement.objects.filter(
                call_time=call_time,
                labor_type=labor_requirement.labor_type
            ).first()
            if existing:
                message = f"Labor requirement for {labor_requirement.labor_type.name} already exists for this call time."
                context = {'form': form, 'call_time': call_time, 'message': message}
                return render(request, 'callManager/add_labor_to_call.html', context)
            labor_requirement.save()
            return redirect('event_detail', slug=call_time.event.slug)
    else:
        form = LaborRequirementForm(company=manager.company, call_time=call_time)
        labor_types = LaborType.objects.filter(company=manager.company)
    context = {'form': form, 'call_time': call_time, 'labor_types': labor_types}
    return render(request, 'callManager/add_labor_to_call.html', context)

@login_required
def edit_call_time(request, slug):
    manager = request.user.manager
    company = manager.company
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    if request.method == "POST":
        form = CallTimeForm(request.POST, instance=call_time, event=call_time.event)
        if form.is_valid():
            updated_call_time = form.save(commit=False)
            if call_time.has_changed():
                confirmed_requests = LaborRequest.objects.filter(
                    labor_requirement__call_time=call_time,
                    confirmed=True,
                ).select_related('worker')
                if confirmed_requests:
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                    sms_errors = []
                    for req in confirmed_requests:
                        worker = req.worker
                        if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                            # Create a confirmation token
                            confirmation = TimeChangeConfirmation.objects.create(
                                labor_request=req,
                                expires_at=timezone.now() + timedelta(days=7)
                            )
                            confirm_url = request.build_absolute_uri(
                                reverse('confirm_time_change', args=[str(confirmation.token)])
                            )
                            message_body = (
                                f"{company.name_short}: {call_time.event.event_name} {call_time.name} time changed. "
                                f"Now: {updated_call_time.date.strftime('%B %d')} at {updated_call_time.time.strftime('%I:%M %p')}. "
                                f"Confirm: {confirm_url}"
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
                    if sms_errors:
                        messages.warning(request, f"Some notifications failed: {', '.join(sms_errors)}")
                    else:
                        messages.success(request, "Call time updated and workers notified.")
            updated_call_time.save()
            return redirect('event_detail', slug=call_time.event.slug)
    else:
        form = CallTimeForm(instance=call_time, event=call_time.event)
    context = {'form': form, 'call_time': call_time}
    return render(request, 'callManager/edit_call_time.html', context)

@login_required
def delete_call_time(request, slug):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    if request.method == "POST":
        call_time.delete()
        return redirect('event_detail', slug=call_time.event.slug)
    return redirect('event_detail', slug=call_time.event.slug)  # Fallback for GET

@login_required
def call_time_request_list(request, slug):
    if not hasattr(request.user, 'administrator') and not hasattr(request.user, 'manager'):
        return redirect('login')
    if hasattr(request.user, 'administrator'):
        call_time = get_object_or_404(CallTime, slug=slug) 
        company = call_time.event.company
    else:
        manager = request.user.manager
        company = manager.company
        call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        requested=True
    ).select_related('worker', 'labor_requirement__labor_type')
    event = call_time.event
    labor_type_filter = request.GET.get('labor_type', 'All')
    if labor_type_filter != 'All':
        labor_requests = labor_requests.filter(labor_requirement__labor_type__id=labor_type_filter)
    if request.method == "POST":
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
        if 'request_id' in request.POST:
            request_id = request.POST.get('request_id')
            action = request.POST.get('action')
            if request_id and action in ['confirm', 'decline', 'ncns', 'delete', 'call_filled']:
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
                worker = labor_request.worker
                was_ncns = labor_request.availability_response == 'ncns'
                if action == 'confirm':
                    call_time = labor_request.labor_requirement.call_time
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
                                    f"Details in the link: {confirmation_url}"
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
                        labor_request.confirmed = True
                        labor_request.save()
                if action == 'ncns':
                    worker.nocallnoshow += 1
                    worker.save()
                elif was_ncns and action in ['confirm', 'decline', 'delete'] and worker.nocallnoshow > 0:
                    worker.nocallnoshow -= 1
                    worker.save()
                if action == 'delete':
                    labor_request.delete()
                    messages.success(request, "Request deleted successfully.")
                else:
                    labor_request.response = 'yes' if action == 'confirm' else 'no' if action == 'decline' else 'ncns'
                    labor_request.responded_at = timezone.now()
                    labor_request.sms_sent = True
                    labor_request.save()
                    messages.success(request, f"Request marked as {action.capitalize()} successfully.")
        return redirect('call_time_request_list', slug=slug)
    pending_requests = labor_requests.filter(availability_response__isnull=True)
    available_requests = labor_requests.filter(availability_response='yes', confirmed=False)
    confirmed_requests = labor_requests.filter(confirmed=True)
    declined_requests = labor_requests.filter(availability_response='no')
    ncns_requests = labor_requests.filter(availability_response='ncns')
    labor_types = LaborType.objects.filter(laborrequirement__call_time=call_time).distinct()
    message = request.GET.get('message', '')
    context = {
        'call_time': call_time,
        'pending_requests': pending_requests,
        'available_requests': available_requests,
        'confirmed_requests': confirmed_requests,
        'declined_requests': declined_requests,
        'ncns_requests': ncns_requests,
        'labor_types': labor_types,
        'selected_labor_type': labor_type_filter,
        'message': message,
    }
    return render(request, 'callManager/call_time_request_list.html', context)

@login_required
def call_time_tracking(request, slug):
    if not hasattr(request.user, 'administrator') and not hasattr(request.user, 'manager'):
        return redirect('login')
    if hasattr(request.user, 'administrator'):
        call_time = get_object_or_404(CallTime, slug=slug) 
        company = call_time.event.company
    else:
        manager = request.user.manager
        company = manager.company
        call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        confirmed=True).select_related('worker', 'labor_requirement__labor_type')
    labor_type_filter = request.GET.get('labor_type', 'All')
    if labor_type_filter != 'All':
        labor_requests = labor_requests.filter(labor_requirement__labor_type__id=labor_type_filter)
    if request.method == "POST":
        request_id = request.POST.get('request_id')
        action = request.POST.get('action')
        labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
        minimum_hours = labor_request.labor_requirement.minimum_hours or call_time.minimum_hours or call_time.event.location_profile.minimum_hours or company.minimum_hours
        worker = labor_request.worker
        if action in [ 'sign_out', 'ncns', 'call_out', 'update_start_time', 'update_end_time', 'add_meal_break', 'update_meal_break']:
            time_entry, created = TimeEntry.objects.get_or_create(
                labor_request=labor_request,
                worker=worker,
                call_time=call_time,
                defaults={'start_time': datetime.combine(call_time.date, call_time.time)})
            was_ncns = worker.nocallnoshow > 0 and labor_request.availability_response == 'no'
#            if action == 'sign_in' and not time_entry.start_time:
#                now = datetime.now()
#                time_entry.start_time = now
#                time_entry.save()
#                messages.success(request, f"Signed in {worker.name}")
            if action == 'sign_out' and time_entry.start_time and not time_entry.end_time:
                end_time = datetime.now()
                if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
                    end_time = time_entry.start_time + timedelta(hours=minimum_hours)
                minutes = end_time.minute
                if minutes > 35:
                    end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                elif minutes > 5:
                    end_time = end_time.replace(minute=30, second=0, microsecond=0)
                else:
                    end_time = end_time.replace(minute=0, second=0, microsecond=0)
                time_entry.end_time = end_time
                time_entry.save()
                messages.success(request, f"Signed out {worker.name}")
            elif action == 'ncns' and not was_ncns:
                labor_request.confirmed = False
                labor_request.availability_response = 'no'
                labor_request.responded_at = datetime.now()
                labor_request.sms_sent = True
                labor_request.save()
                worker.nocallnoshow += 1
                worker.save()
                messages.success(request, f"Marked {worker.name} as NCNS")
            elif action == 'call_out':
                if was_ncns and worker.nocallnoshow > 0:
                    worker.nocallnoshow -= 1
                    worker.save()
                labor_request.delete()
                messages.success(request, f"{worker.name} marked as called out")
            elif action == 'add_meal_break' and time_entry.start_time:
                break_time = datetime.now()
                minutes = break_time.minute
                if minutes > 35:
                    break_time = break_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                elif minutes > 5:
                    break_time = break_time.replace(minute=30, second=0, microsecond=0)
                else:
                    break_time = break_time.replace(minute=0, second=0, microsecond=0)
                break_type = request.POST.get('break_type', 'paid')
                duration = timedelta(hours=1) if break_type == 'unpaid' else None
                meal_break = MealBreak.objects.create(
                    time_entry=time_entry,
                    break_time=break_time,
                    break_type=break_type,
                    duration=duration)
                if request.headers.get('HX-Request'):
                    context = {'call_time': call_time, 'meal_break': meal_break}
                    return render(request, 'callManager/meal_break_display_partial.html', context)
                messages.success(request, f"Added {break_type} meal break for {worker.name}")
            elif action == 'update_meal_break':
                meal_break_id = request.POST.get('meal_break_id')
                meal_break = get_object_or_404(MealBreak, id=meal_break_id, time_entry=time_entry)
                time_str = request.POST.get('time')
                date_str = request.POST.get('date')
                error_message = None
                try:
                    hour, minute = map(int, time_str.split(':'))
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                    new_time = datetime.combine(date_obj, time(hour, minute))
                    start_date = time_entry.start_time.date()
                    end_date = time_entry.end_time.date() if time_entry.end_time else datetime.now().date()
                    if start_date <= date_obj <= end_date and time_entry.start_time <= new_time and (not time_entry.end_time or new_time <= time_entry.end_time):
                        meal_break.break_time = new_time
                        meal_break.save()
                        if request.headers.get('HX-Request'):
                            context = {'call_time': call_time, 'meal_break': meal_break}
                            return render(request, 'callManager/meal_break_display_partial.html', context)
                        messages.success(request, f"Updated meal break for {worker.name}")
                    else:
                        error_message = "Meal break time must be within the shift duration"
                except (ValueError, TypeError) as e:
                    error_message = "Invalid date or time format for meal break"
                if request.headers.get('HX-Request'):
                    context = {
                        'call_time': call_time,
                        'meal_break': meal_break,
                        'error_message': error_message}
                    return render(request, 'callManager/meal_break_display_partial.html', context)
                if error_message:
                    messages.error(request, error_message)
                else:
                    messages.success(request, f"Updated meal break for {worker.name}")
            elif action in ['update_start_time', 'update_end_time']:
                time_entry_id = request.POST.get('time_entry_id')
                time_entry = get_object_or_404(TimeEntry, id=time_entry_id, labor_request=labor_request)
                time_str = request.POST.get('time')
                date_str = request.POST.get('date')
                try:
                    hour, minute = map(int, time_str.split(':'))
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                    new_time = datetime.combine(date_obj, time(hour, minute))
                    if action == 'update_start_time':
                        time_entry.start_time = new_time
                    else:
                        if minute > 5:
                            new_time = new_time.replace(minute=30)
                        else:
                            new_time = new_time.replace(minute=0)
                        time_entry.end_time = new_time
                    time_entry.save()
                    if request.headers.get('HX-Request'):
                        context = {'call_time': call_time, 'labor_request': labor_request, 'field': action.replace('update_', '')}
                        return render(request, 'callManager/time_entry_display_partial.html', context)
                    messages.success(request, f"Updated {action.replace('update_', '')} for {worker.name}")
                except (ValueError, TypeError):
                    messages.error(request, f"Invalid date or time format")
            elif action == 'delete_meal_break':
                meal_break_id = request.POST.get('meal_break_id')
                meal_break = get_object_or_404(MealBreak, id=meal_break_id, time_entry=time_entry)
                print(meal_break)
                meal_break.delete()
                messages.success(request, f"Deleted meal break for {worker.name}")
                return HttpResponse(" ")
        if not request.headers.get('HX-Request'):
            return redirect('call_time_tracking', slug=slug)
    confirmed_requests = labor_requests
    ncns_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        confirmed=False,
        availability_response='no',
        worker__nocallnoshow__gt=0).select_related('worker', 'labor_requirement__labor_type')
    if labor_type_filter != 'All':
        ncns_requests = ncns_requests.filter(labor_requirement__labor_type__id=labor_type_filter)
    labor_types = LaborType.objects.filter(laborrequirement__call_time=call_time).distinct()
    hours = range(24)
    minutes = ['00', '30']
    context = {
        'call_time': call_time,
        'confirmed_requests': confirmed_requests,
        'ncns_requests': ncns_requests,
        'labor_types': labor_types,
        'selected_labor_type': labor_type_filter,
        'hours': hours,
        'minutes': minutes}
    return render(request, 'callManager/call_time_tracking.html', context)

@login_required
def call_time_tracking_edit(request, slug):
    call_time = get_object_or_404(CallTime, slug=slug)
    request_id = request.GET.get('request_id')
    field = request.GET.get('field')
    labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
    time_entry = labor_request.time_entries.first()
    hours = range(24)
    minutes = ['00', '30']
    context = {
        'call_time': call_time,
        'time_entry': time_entry,
        'field': field,
        'hours': hours,
        'minutes': minutes
    }
    return render(request, 'callManager/time_entry_edit_partial.html', context)

@login_required
def htmx_time_sheet_row(request, id):
    labor_request = get_object_or_404(LaborRequest, id=id)
    worker = labor_request.worker
    call_time = labor_request.labor_requirement.call_time
    labor_requirement = labor_request.labor_requirement
    minimum_hours = labor_requirement.minimum_hours
    round_up = call_time.event.location_profile.hour_round_up or company.hour_round_up
    company = call_time.event.company
    start_time = call_time.time
    date = call_time.date
    time_entry, created = TimeEntry.objects.get_or_create(
        labor_request=labor_request,
        worker=labor_request.worker,
        call_time=labor_request.labor_requirement.call_time,
        defaults={'start_time': datetime.combine(labor_request.labor_requirement.call_time.date, labor_request.labor_requirement.call_time.time)})
    meal_breaks = time_entry.meal_breaks.all()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'sign_in' and not time_entry.start_time:
            time_entry.start_time = datetime.combine(date, start_time)
            time_entry.save()
            messages.success(request, f"Signed in at {time_entry.start_time.strftime('%I:%M %p')}.")
        elif action == 'sign_out' and time_entry.start_time and not time_entry.end_time:
            if not time_entry.start_time:
                time_entry.start_time = datetime.combine(date, start_time)
                time_entry.save()
            end_time = datetime.now()
            if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
                end_time = time_entry.start_time + timedelta(hours=minimum_hours)
            minutes = end_time.minute
            if minutes > 30 + round_up:
                end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            elif minutes > round_up:
                end_time = end_time.replace(minute=30, second=0, microsecond=0)
            else:
                end_time = end_time.replace(minute=0, second=0, microsecond=0)
            time_entry.end_time = end_time
            time_entry.save()
            messages.success(request, f"Signed out at {time_entry.end_time.strftime('%I:%M %p')}.")
        elif action == 'add_meal_break':
            break_start = datetime.now()
            if break_start.minute > 30 + round_up:
                break_start = break_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            elif break_start.minute > round_up:
                break_start = break_start.replace(minute=30, second=0, microsecond=0)
            else:
                break_start = break_start.replace(minute=0, second=0, microsecond=0)
            break_type = request.POST.get('break_type', 'paid')
            duration = timedelta(hours=1) if break_type == 'unpaid' else timedelta(minutes=30)
            meal_break = MealBreak.objects.create(
                time_entry=time_entry,
                break_time=break_start,
                break_type=break_type,
                duration=duration)
            messages.success(request, f"Added {break_type} meal break for {labor_request.worker.name}")
        elif action == 'update_meal_break':
            meal_break_id = request.POST.get('meal_break_id')
            meal_break = get_object_or_404(MealBreak, id=meal_break_id, time_entry=time_entry)
            break_time = datetime.now()
            if break_time.minute > 30 + round_up:
                break_time = break_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            elif break_time.minute > round_up:
                break_time = break_time.replace(minute=30, second=0, microsecond=0)
            else:
                break_time = break_time.replace(minute=0, second=0, microsecond=0)
            meal_break.break_time = break_time
            meal_break.save()
            messages.success(request, f"Updated meal break for {labor_request.worker.name}")
        elif action == 'ncns':
            labor_request.confirmed = False
            labor_request.availability_response = 'no'
            labor_request.save()
            worker.nocallnoshow += 1
            worker.save()
            return HttpResponse(" ")
        elif action == 'call_out':
            labor_request.confirmed = False
            labor_request.availability_response = 'no'
            labor_request.save()
            labor_request.delete()
            return HttpResponse(" ")
    context = {
        'time_entry': time_entry,
        'meal_breaks': meal_breaks,
        'call_time': call_time,
        'worker': labor_request.worker,
        'labor_request': labor_request
    }
    return render(request, 'callManager/time_sheet_row_partial.html', context)

@login_required
def copy_call_time(request, slug):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    event = call_time.event
    if request.method == "POST":
        form = CallTimeForm(request.POST, event=event)
        if form.is_valid():
            new_call_time = form.save(commit=False)
            new_call_time.event = event
            new_call_time.slug = None  # Generate new slug
            new_call_time.original_date = new_call_time.date
            new_call_time.original_time = new_call_time.time
            new_call_time.save()
            # Copy labor requirements
            for labor_requirement in call_time.labor_requirements.all():
                new_labor_requirement = LaborRequirement.objects.create(
                    call_time=new_call_time,
                    labor_type=labor_requirement.labor_type,
                    needed_labor=labor_requirement.needed_labor,
                    minimum_hours=labor_requirement.minimum_hours,
                    fcfs_positions=labor_requirement.fcfs_positions
                )
                # Copy labor requests as "requested" without response data
                for labor_request in labor_requirement.labor_requests.all():
                    LaborRequest.objects.create(
                        worker=labor_request.worker,
                        labor_requirement=new_labor_requirement,
                        token_short=generate_short_token(), 
                        requested=True,
                        sms_sent=False,
                        is_reserved=labor_request.is_reserved
                    )
            messages.success(request, f"Call time '{call_time.name}' copied successfully.")
            return redirect('event_detail', slug=event.slug)
    else:
        form = CallTimeForm(initial={
            'name': call_time.name,
            'date': call_time.date,
            'time': call_time.time,
            'minimum_hours': call_time.minimum_hours,
            'message': call_time.message
        }, event=event)
    context = {'form': form, 'call_time': call_time, 'event': event}
    return render(request, 'callManager/copy_call_time.html', context)

def confirm_time_change(request, token):
    try:
        confirmation = TimeChangeConfirmation.objects.get(
            token=token,
            expires_at__gt=timezone.now(),
            confirmed=False
        )
        confirmation.confirmed = True
        confirmation.labor_request.time_change_confirmed = True
        confirmation.labor_request.save()
        confirmation.save()
        messages.success(request, "Time change confirmed successfully.")
    except TimeChangeConfirmation.DoesNotExist:
        messages.error(request, "Invalid or expired confirmation link.")
    return render(request, 'callManager/confirm_time_change.html')

@login_required
def call_time_confirmations(request, slug):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    call_time = get_object_or_404(CallTime, slug=slug, event__company=request.user.manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        confirmed=True
    ).select_related('worker', 'labor_requirement__labor_type')
    confirmed_requests = labor_requests.filter(time_change_confirmed=True)
    unconfirmed_requests = labor_requests.filter(time_change_confirmed=False)
    context = {
        'call_time': call_time,
        'confirmed_requests': confirmed_requests,
        'unconfirmed_requests': unconfirmed_requests,
    }
    return render(request, 'callManager/call_time_confirmations.html', context)

