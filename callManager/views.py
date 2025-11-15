#models
from time import sleep
from .models import (
        CallTime,
        LaborRequest,
        Event,
        LaborRequirement,
        LaborType,
        Notifications,
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
from .forms import (
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


# channels imports
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# posssibly imports
import pytz
import io

import logging

# Create a logger instance
logger = logging.getLogger('callManager')


def custom_404(request, exception):
    return render(request, 'callManager/404.html', status=404)

def custom_500(request):
    return render(request, 'callManager/500.html', status=500)

def custom_403(request, exception):
    return render(request, 'callManager/403.html', status=403)

def custom_400(request, exception):
    return render(request, 'callManager/400.html', status=400)

def index(request):
    return render(request, 'callManager/index.html')

def log_sms(company):
    """logs the SMS sent to the SentSMS model"""
    if company == None:
        return
    sms = SentSMS.objects.create(company=company)
    sms.save()


# this view is dead and shold be removed soon
def confirm_assignment(request, token):
    assignment = get_object_or_404(LaborRequest, token=token)
    if request.method == "POST":
        load_in_response = request.POST.get('load_in_response')
        load_out_response = request.POST.get('load_out_response')
        response_message = request.POST.get('response_message', '')
        assignment.load_in_response = load_in_response
        assignment.load_out_response = load_out_response
        if 'other' in (load_in_response, load_out_response):
            assignment.response_message = response_message
        assignment.responded_at = timezone.now()
        assignment.save()
        return render(request, 'callManager/confirmation_success.html', {'assignment': assignment})
    return render(request, 'callManager/confirmation_form.html', {'assignment': assignment})


def generate_short_token(length=6):
    """Generate a random alphanumeric token of specified length."""
    characters = string.ascii_letters + string.digits  # a-z, A-Z, 0-9
    return ''.join(random.choice(characters) for _ in range(length))


def send_message(message_body, worker, manager=None, company=None):
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
    sms_errors = []
    message_length = len(message_body)
    if worker.stop_sms:
        sms_errors.append(f"{worker.name} (opted out via STOP)")
    elif not worker.sms_consent and not worker.sent_consent_msg:
        if manager and company:
            consent_body = f"This is {manager.user.first_name} with {company.name}.\nWe're using Callman to send out gigs. Reply 'Yes.' to receive job requests\nReply 'No.' or 'STOP' to opt out."
        else:
            consent_body = f"Reply 'Yes.' to receive job requests\nReply 'No.' or 'STOP' to opt out."
        if settings.TWILIO_ENABLED == 'enabled' and client:
            try:
                client.messages.create(
                    body=consent_body,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=str(worker.phone_number)
                )
                worker.sent_consent_msg = True
                worker.save()
            except TwilioRestException as e:
                sms_errors.append(f"Consent SMS failed for {worker.name}: {str(e)}")
            finally:
                log_sms(company)
        else:
            log_sms(company)
            worker.sent_consent_msg = True
            worker.save()
            print(consent_body)
    elif worker.sms_consent:
        if settings.TWILIO_ENABLED == 'enabled' and client:
            try:
                client.messages.create(
                    body=message_body,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=str(worker.phone_number)
                )
            except TwilioRestException as e:
                sms_errors.append(f"SMS failed for {worker.name}: {str(e)}")
            finally:
                log_sms(company)
                while message_length > 144:
                    log_sms(company)
                    message_length -= 144
        else:
            log_sms(company)
            while message_length > 144:
                log_sms(company)
                message_length -= 144
            print(message_body)
    else:
        sms_errors.append(f"{worker.name} (awaiting consent)")
    return sms_errors


@login_required
def labor_type_partial(request, slug):
    manager = request.user.manager
    labor_type = get_object_or_404(LaborType, slug=slug, company=manager.company)
    if request.method == "POST":
        form = LaborTypeForm(request.POST, instance=labor_type)
        if form.is_valid():
            form.save()
            return redirect('view_skills')
    else:
        form = LaborTypeForm(instance=labor_type)
    context = {'form': form, 'labor_type': labor_type}
    return render(request, 'callManager/labor_type_partial.html', context)


@csrf_exempt
def sms_webhook(request):
    stop_list = ['stop', 'optout', 'cancel', 'end', 'quit', 'unsubscribe', 'revoke', 'stopall']
    go_list = ['yes', 'start', 'go', 'resume', 'subscribe']
    if request.method == "POST":
        from_number = request.POST.get('From')
        body = request.POST.get('Body', '').strip().lower()
        workers = Worker.objects.filter(phone_number=from_number)
        response = MessagingResponse()
        for worker in workers:
            print(worker.name)
        if not workers.exists():
            response.message("Number not recognized. Please contact your Steward")
            return HttpResponse(str(response), content_type='text/xml')
        # Check if any worker has stopped SMS
        if any(worker.stop_sms for worker in workers) and not body in go_list:
            response.message("You’ve been unsubscribed from CallMan messages. Reply 'START' to resume.")
            return HttpResponse(str(response), content_type='text/xml')
        if body.startswith('yes') or body == 'y' or body == 'start':
            consent_state = True
            for worker in workers: 
                if worker.sms_consent != True:
                    consent_state = False
            if consent_state == True:
                response.message( "You're already set. Sending 'yes' doesn't do anything here. Click the link to confirm availability." )
            else:
                response.message("Thank you! You’ll now receive job requests.")
            for worker in workers:
                worker.sms_consent = True
                worker.stop_sms = False
                worker.save()
            # Process queued labor requests for all workers
            queued_requests = LaborRequest.objects.filter(
                worker__in=workers,
                requested=True,
                sms_sent=False
            ).select_related('worker', 'labor_requirement__call_time__event', 'labor_requirement__call_time__event__company')
            if queued_requests.exists():
                # Group requests by event only
                events_to_notify = {}
                for req in queued_requests:
                    event = req.labor_requirement.call_time.event
                    if event.id not in events_to_notify:
                        events_to_notify[event.id] = {'event': event, 'company': event.company, 'requests': []}
                    events_to_notify[event.id]['requests'].append(req)
                # Send one message per event
                for _, data in events_to_notify.items():
                    event = data['event']
                    company = data['company']
                    requests = data['requests']
                    # Use existing token_short if available, otherwise generate new
                    token = next((req.token_short for req in requests if req.token_short), generate_short_token())
                    confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                    response.message(
                        f"This is {company.name}: Confirm availability for {event.event_name} "
                        f"on {event.start_date}: {confirmation_url}"
                    )
                    # Update all requests for this event with the same token
                    for req in requests:
                        req.sms_sent = True
                        req.token_short = token
                        req.save()
            
        elif body in stop_list:
            for worker in workers:
                worker.sms_consent = False
                worker.stop_sms = True
                worker.save()
        else:
            # Catchall response based on sms_consent
            if any(not worker.sms_consent for worker in workers):
                response.message("Response not recognized. Please reply 'Yes' or 'Y' to consent to SMS notifications, or 'STOP' to unsubscribe.")
            else:
                response.message("This is an automated system. No one is reading your response. Reply 'STOP' to unsubscribe.")
        return HttpResponse(str(response), content_type='text/xml')
    return HttpResponse(status=400)


def confirm_event_requests(request, slug, event_token):
    event = get_object_or_404(Event, slug=slug)
    company = event.company
    if len(event_token) > 6:
        first_request = LaborRequest.objects.filter(
            labor_requirement__call_time__event=event,
            event_token=event_token,
            worker__phone_number__isnull=False).select_related('worker').first()
    else:
        first_request = LaborRequest.objects.filter(
            labor_requirement__call_time__event=event,
            token_short=event_token,
            worker__phone_number__isnull=False).select_related('worker').first()
    if not first_request:
        context = {'message': 'No requests found for this link.'}
        return render(request, 'callManager/confirm_error.html', context)
    worker = first_request.worker
    worker_phone = worker.phone_number
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        requested=True,
        availability_response__isnull=True,
        worker__phone_number=worker_phone).select_related(
        'labor_requirement__call_time',
        'labor_requirement__labor_type').annotate(
        confirmed_count=Count('labor_requirement__labor_requests', filter=Q(labor_requirement__labor_requests__confirmed=True))).order_by(
        'labor_requirement__call_time__date',
        'labor_requirement__call_time__time')
    confirmed_call_times = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        confirmed=True,
        worker__phone_number=worker_phone).select_related(
        'labor_requirement__call_time',
        'labor_requirement__labor_type').order_by(
        'labor_requirement__call_time__date',
        'labor_requirement__call_time__time')
    available_call_times = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        availability_response='yes',
        confirmed=False,
        worker__phone_number=worker_phone).select_related(
        'labor_requirement__call_time',
        'labor_requirement__labor_type').order_by(
        'labor_requirement__call_time__date',
        'labor_requirement__call_time__time')
    registration_url = request.build_absolute_uri(f"/user/register/?phone={worker_phone}")
    calendar_links = []
    for req in confirmed_call_times:
        call_time = req.labor_requirement.call_time
        start_dt = datetime.combine(call_time.date, call_time.time)
        end_dt = start_dt + timedelta(hours=4)
        event_name = quote(f"{event.event_name} - {call_time.name}")
        location = quote(event.location_profile.name if event.location_profile else "TBD")
        details = quote(f"Position: {req.labor_requirement.labor_type.name}\nConfirmed for {worker.name}")
        gcal_url = (
            f"https://calendar.google.com/calendar/r/eventedit?"
            f"text={event_name}&"
            f"dates={start_dt.strftime('%Y%m%dT%H%M%S')}/{end_dt.strftime('%Y%m%dT%H%M%S')}&"
            f"details={details}&"
            f"location={location}")
        calendar_links.append({
            'call_time': call_time,
            'position': req.labor_requirement.labor_type.name,
            'message': call_time.message if call_time.message else '',
            'gcal_url': gcal_url})
    qr_code_data = None
    if calendar_links:
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
        qr_code_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
    if request.method == "POST":
        sms_errors = []
        for labor_request in labor_requests:
            worker = labor_request.worker
            company = event.company
            call_time = labor_request.labor_requirement.call_time
            labor_type = labor_request.labor_requirement.labor_type
            response_key = f"response_{labor_request.id}"
            response = request.POST.get(response_key)
            if response in ['yes', 'no']:
                labor_request.availability_response = response
                labor_request.responded_at = timezone.now()
                labor_request.save()
                if response == 'yes' and not labor_request.labor_requirement.fcfs_positions > 0 and not labor_request.is_reserved:
                    notif_message = f"{worker.name} Available for {event.event_name} - {call_time.name} - {labor_type.name}, Requires confirmation"
                    print(notif_message)
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                if response == 'yes' and labor_request.labor_requirement.fcfs_positions > 0 and not labor_request.is_reserved:
                    notif_message = f"{worker.name} confirmed for {event.event_name} - {call_time.name} - {labor_type.name}"
                    confirmed_count = LaborRequest.objects.filter(
                        labor_requirement=labor_request.labor_requirement,
                        confirmed=True).count()
                    if confirmed_count < labor_request.labor_requirement.fcfs_positions:
                        labor_request.confirmed = True
                        labor_request.save()
                        call_time = labor_request.labor_requirement.call_time
                        if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                            message_body = (
                                f"Confirmed {labor_request.labor_requirement.labor_type} "
                                f"for {event.event_name} - {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d')}")
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
                elif response == 'yes' and labor_request.is_reserved:
                    notif_message = f"{worker.name} confirmed for {event.event_name} - {call_time.name} - {labor_type.name}"
                    labor_request.confirmed = True
                    labor_request.save()
                    call_time = labor_request.labor_requirement.call_time
                    if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                        message_body = (
                            f"Confirmed {labor_request.labor_requirement.labor_type} "
                            f"for {event.event_name} - {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d')}")
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
                elif response == 'no' and labor_request.is_reserved:
                    notif_message = f"{worker.name} declined {event.event_name} - {call_time.name} - {labor_type.name}"
                    labor_request.is_reserved = False
                    labor_request.save()
                    confirmed_count = LaborRequest.objects.filter(
                        labor_requirement=labor_request.labor_requirement,
                        confirmed=True).count()
                    if confirmed_count < labor_request.labor_requirement.fcfs_positions:
                        available_fcfs = LaborRequest.objects.filter(
                            labor_requirement=labor_request.labor_requirement,
                            availability_response='yes',
                            confirmed=False,
                            is_reserved=False).exclude(id=labor_request.id).order_by('responded_at').first()
                        if available_fcfs:
                            available_fcfs.confirmed = True
                            available_fcfs.save()
                if notif_message:
                    notify(labor_request.id, notif_message)
        if sms_errors:
            messages.warning(request, f"Some SMS failed: {', '.join(sms_errors)}")
        context = {
            'company': company,
            'event': event,
            'registration_url': registration_url,
            'confirmed_call_times': calendar_links,
            'available_call_times': available_call_times,
            'qr_code_data': qr_code_data}
        return render(request, 'callManager/confirm_success.html', context)
    context = {
        'company': company,
        'event': event,
        'labor_requests': labor_requests,
        'registration_url': registration_url,
        'available_call_times': available_call_times,
        'confirmed_call_times': calendar_links,
        'qr_code_data': qr_code_data}
    if not labor_requests.exists() and not available_call_times.exists() and not calendar_links:
        context['message'] = "No requests found for this link."
        return render(request, 'callManager/confirm_error.html', context)
    return render(request, 'callManager/confirm_event_requests.html', context)


@login_required
def send_clock_in_link(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    confirmed_workers = Worker.objects.filter(
        labor_requests__labor_requirement__call_time__event=event,
        labor_requests__confirmed=True).distinct()
    sms_errors = []
    for worker in confirmed_workers:
        token, created = ClockInToken.objects.get_or_create(
            event=event,
            worker=worker,
            defaults={'expires_at': timezone.now() + timedelta(days=1), 'qr_sent': False})
        if token.qr_sent:
            continue
        qr_code_url = request.build_absolute_uri(reverse('display_qr_code', args=[event.slug, worker.slug]))
        message_body = (
            f"{manager.company.name}: Your clock-in QR code for {event.event_name}. "
            f"View: {qr_code_url}"
            )
        sms_errors = send_message(message_body, worker, manager, manager.company)
        if not sms_errors:
            token.qr_sent = True
            token.save()
    if sms_errors:
        messages.warning(request, f"Some SMS failed: {', '.join(sms_errors)}")
    else:
        messages.success(request, "Clock-in QR code links sent to workers.")
    return redirect('event_detail', slug=event.slug)


@require_GET
def get_messages(request):
    """Return only the messages partial for HTMX requests"""
    # Get messages from the request
    sleep(0.5)
    messages_list = django_get_messages(request)
    response = render(request, 'callManager/floating_messages_partial.html', {'messages': messages_list})
    # Add a custom header to identify this response
    response['X-Messages-Response'] = 'true'
    return response


def add_worker(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return redirect('login')
    manager = user.manager
    company = manager.company
    if request.method == "POST":
        form = WorkerForm(request.POST)
        if form.is_valid():
            worker = form.save(commit=False)
            worker.save()
            consent_body = f"This is {user.first_name} with {company.name_short}. Reply 'Yes.' to receive jobs through CallMan. Reply 'No.' or 'STOP' to opt out."
            if settings.TWILIO_ENABLED == 'enabled':
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                try:
                    client.messages.create(
                        body=consent_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=str(worker.phone_number)
                    )
                    worker.sent_consent_msg = True
                    worker.save()
                    log_sms(company)
                    messages.success(request, f"Worker '{worker.name}' added and consent message sent.")
                except TwilioRestException as e:
                    messages.error(request, f"Failed to send consent message: {str(e)}")
            else:
                log_sms(company)
                print(consent_body)
                worker.sent_consent_msg = True
                worker.save()
                messages.success(request, f"Worker '{worker.name}' added (SMS disabled).")
            return redirect('add_worker')  # Stay on the page for more entries
    else:
        form = WorkerForm()
    return render(request, 'callManager/add_worker.html', {'form': form})

def dashboard_redirect(request):
    if hasattr(request.user, 'administrator'):
        return redirect('admin_dashboard')
    elif hasattr(request.user, 'manager'):
        return redirect('manager_dashboard')
    elif hasattr(request.user, 'steward'):
        return redirect('steward_dashboard')
    else:
        return redirect('user_profile')


def notify(labor_request_id, message):

    labor_request = get_object_or_404(LaborRequest, id=labor_request_id)
    labor_requirement = labor_request.labor_requirement
    call_time = labor_requirement.call_time
    event = call_time.event
    company = event.company

    notification = Notifications.objects.create(
        company=company,
        event=event,
        call_time=call_time,
        labor_requirement=labor_requirement,
        labor_request=labor_request,
        message=message,
        read=False,
    )
    notification.save()
    push_notification(company)
    return

def push_notification(company):
    # Send via WebSocket to all users in the company
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"company_{company.id}_notifications",
        {
            "type": "send.notification",
            "notification": {
                "type": "send_notification",  # maps to send_notification() in consumer
            }
        }
    )
    return


@login_required
def notifications(request):
    if not hasattr(request.user, 'manager'):
        return
    company = request.user.manager.company
    notifications = Notifications.objects.filter(
        company=request.user.manager.company).order_by('-sent_at')
    channel_layer = get_channel_layer()
    if request.method == "POST":
        action = request.POST.get('action')
        if action == 'mark_read':
            notification_id = request.POST.get('notification_id')
            notification = get_object_or_404(Notifications, id=notification_id)
            notification.read = True
            notification.save()
            push_notification(company)

        if action == 'mark_all_read':
            notifications.update(read=True)
            push_notification(company)
        if action == 'delete':
            notification_id = request.POST.get('notification_id')
            notification = get_object_or_404(Notifications, id=notification_id)
            notification.delete()
            push_notification(company)
        if action == 'delete_all':
            notifications.delete()
            push_notification(company)
    context = {'notifications': notifications}
    return render(request, 'callManager/notifications.html', context)

def htmx_get_notification_count(request):
    if not hasattr(request.user, 'manager'):
        return HttpResponse("")  # or empty

    company = request.user.manager.company
    count = Notifications.objects.filter(company=company, read=False).count()

    # Check for *very recent* notifications to trigger messages.success
    recent = Notifications.objects.filter(
        company=company,
        read=False,
        sent_at__gte=timezone.now() - timedelta(seconds=10)
    )
    for n in recent:
        messages.success(request, n.message)

    context = {'count': count}
    template = 'callManager/notification_button_count.html' if count > 0 else 'callManager/notifications_button_empty.html'
    return render(request, template, context)

def htmx_clear(request):
    return HttpResponse("")
