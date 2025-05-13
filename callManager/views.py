#models
from time import sleep
from .models import (
        CallTime,
        LaborRequest,
        Event,
        LaborRequirement,
        LaborType,
        OneTimeLoginToken,
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
        LaborTypeForm,
        LaborRequirementForm,
        EventForm,
        WorkerForm,
        WorkerImportForm,
        WorkerRegistrationForm,
        SkillForm,
        OwnerRegistrationForm,
        CompanyForm,
        LocationProfileForm,
        )
# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.http import base64
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, time, timedelta
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.contrib.messages import get_messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import FileResponse
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView

# Twilio imports
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# repotlab imports for PDF generation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Table, TableStyle, Paragraph, SimpleDocTemplate
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# other imports
import qrcode
from io import BytesIO, TextIOWrapper
import re
import uuid
from urllib.parse import urlencode, quote
from user_agents import parse

# posssibly imports
import pytz
import io


def index(request):
    return render(request, 'callManager/index.html')

def custom_404(request, exception):
    return render(request, 'callManager/404.html', status=404)

def fetch_messages(request):
    storage = get_messages(request)
    messages = [msg for msg in storage]
    context = {
        'messages': messages,
        'error_message': request.session.pop('error_message', None),
        'success_message': request.session.pop('success_message', None),
    }
    for message in messages:
        storage.used = True
    return render(request, 'callManager/partial_messages.html', context)

def log_sms(company):
    """logs the SMS sent to the SentSMS model"""
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


@login_required
def event_detail(request, slug):
    """event detail page for managers"""
    manager = request.user.manager
    company = manager.company
    event = get_object_or_404(Event, slug=slug, company=manager.company)
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
        queued_requests = LaborRequest.objects.filter(labor_requirement__call_time__event=event, requested=True, sms_sent=False).select_related('worker')
        if queued_requests.exists():
            sms_errors = []
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
            worker_tokens = {}
            # Group requests by worker
            workers_to_notify = {}
            for labor_request in queued_requests:
                worker = labor_request.worker
                if worker.id not in workers_to_notify:
                    workers_to_notify[worker.id] = {'worker': worker, 'requests': []}
                workers_to_notify[worker.id]['requests'].append(labor_request)
            # Send one message per worker
            for worker_id, data in workers_to_notify.items():
                worker = data['worker']
                requests = data['requests']
                if worker.phone_number:
                    if worker.stop_sms:
                        sms_errors.append(f"{worker.name} (opted out via STOP)")
                    elif not worker.sms_consent and not worker.sent_consent_msg:
                        consent_body = "Reply 'Yes.' to receive job request messages from CallMan. Reply 'No.' or 'STOP' to opt out."
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
                    elif worker.sms_consent:
                        token = worker_tokens.get(worker.id, str(uuid.uuid4()))
                        worker_tokens[worker.id] = token
                        confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                        message_body = f"{company.name}: Confirm availability for {event.event_name}: {confirmation_url}"
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
                        else:
                            log_sms(company)
                            print(message_body)
                        # Mark all requests as sent with the same token
                        for labor_request in requests:
                            labor_request.sms_sent = True
                            labor_request.event_token = token
                            labor_request.save()
                    else:
                        sms_errors.append(f"{worker.name} (awaiting consent)")
                else:
                    sms_errors.append(f"{worker.name} (no phone)")
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
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    if request.method == "POST":
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
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
def admin_dashboard(request):
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
    total_events = events.count()
    pending_requests = LaborRequest.objects.filter(
        availability_response__isnull=True).count()
    declined_requests = LaborRequest.objects.filter(
        availability_response='no').count()
    labor_requirements = LaborRequirement.objects.select_related(
        'labor_type', 'call_time__event').annotate(
        confirmed_count=Count('labor_requests', filter=Q(labor_requests__confirmed=True)))
    unfilled_spots = sum(max(0, lr.needed_labor - lr.confirmed_count) for lr in labor_requirements)
    current_date = timezone.now()
    start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_of_month + timedelta(days=32)).replace(day=1)
    sent_messages = SentSMS.objects.filter(
        datetime_sent__gte=start_of_month,
        datetime_sent__lt=next_month).count()
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
    if request.method == "POST":
        phone = request.POST.get('phone')
        if phone and phone != '':
            phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if len(phone) == 10:
                phone = f"+1{phone}"
            elif len(phone) == 11 and phone.startswith('1'):
                phone = f"+{phone}"
            elif len(phone) < 10:
                phone = None
        else:
            phone = None
        if phone:
            invitation = OwnerInvitation.objects.create(phone=phone)
            registration_url = request.build_absolute_uri(reverse('register_owner', args=[str(invitation.token)]))
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
            message_body = f'You are invited to become an owner. Register: {registration_url}'
            if settings.TWILIO_ENABLED == 'enabled' and client:
                try:
                    client.messages.create(
                        body=message_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=phone)
                    log_sms(request.user.manager.company)
                    messages.success(request, f"Invitation sent to {phone}.")
                except TwilioRestException as e:
                    messages.error(request, f"Failed to send invitation: {str(e)}")
            else:
                log_sms(request.user.manager.company)
                print(message_body)
                messages.success(request, f"Invitation printed for {phone}.")
        else:
            messages.error(request, "Please provide a valid phone number.") 
    context = {
        'events': events,
        'total_events': total_events,
        'pending_requests': pending_requests,
        'sent_messages': sent_messages,
        'declined': declined_requests,
        'unfilled_spots': unfilled_spots,
        'event_labor_needs': event_labor_needs,
        'search_query': search_query,
        'include_past': include_past,
        'admindashboard': admindashboard,
        }
    return render(request, 'callManager/admin_dashboard.html', context)

def register_owner(request, token):
    invitation = get_object_or_404(OwnerInvitation, token=token, used=False)
    if request.method == "POST":
        form = OwnerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            company = Company.objects.create(
                name=form.cleaned_data['company_name'],
                phone_number=invitation.phone)
            Owner.objects.create(user=user, company=company)
            Manager.objects.create(user=user, company=company)
            invitation.used = True
            invitation.save()
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, f"Registration successful. You are now an owner and manager of {company.name}.")
            return redirect('manager_dashboard')
    else:
        form = OwnerRegistrationForm()
    context = {'form': form, 'invitation': invitation}
    return render(request, 'callManager/register_owner.html', context)


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
                term_filter = Q(event_name__icontains=term) | Q(event_location__icontains=term)
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
    workers = Worker.objects.filter(companies=company).order_by('name')
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
    workers = Worker.objects.filter(companies=company).order_by('name')
    if search_query:
        workers = workers.filter(Q(name__icontains=search_query) | Q(phone_number__icontains=search_query))
    context = {
        'workers': workers,
        'search_query': search_query}
    return render(request, 'callManager/steward_invite_partial.html', context)


def register_steward(request, token):
    invitation = get_object_or_404(StewardInvitation, token=token, used=False)
    if request.method == "POST":
        form = WorkerRegistrationForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            workers = Worker.objects.filter(phone_number=phone_number)
            if not workers.exists() or invitation.worker not in workers:
                messages.error(request, "No worker found with this phone number or phone number does not match invitation.")
                return render(request, 'callManager/register_steward.html', {'form': form, 'invitation': invitation})
            already_registered = workers.filter(user__isnull=False)
            if already_registered.exists():
                messages.error(request, "One or more workers with this phone number are already registered with a user account.")
                return render(request, 'callManager/register_steward.html', {'form': form, 'invitation': invitation})
            user = form.save()
            Steward.objects.create(user=user, company=invitation.company)
            for worker in workers:
                worker.user = user
                worker.save()
            invitation.used = True
            invitation.save()
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, "Registration successful. You are now a steward.")
            return redirect('steward_dashboard')
    else:
        form = WorkerRegistrationForm(initial={'phone_number': invitation.worker.phone_number})
    context = {'form': form, 'invitation': invitation}
    return render(request, 'callManager/register_steward.html', context)


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
def create_labor_type(request):
    manager = request.user.manager
    if request.method == "POST":
        form = LaborTypeForm(request.POST)
        if form.is_valid():
            labor_type = form.save(commit=False)
            labor_type.company = manager.company
            labor_type.save()
            return redirect('labor_type_list')
    else:
        form = LaborTypeForm()
    return render(request, 'callManager/create_labor_type.html', {'form': form})


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


@login_required
def view_skills(request):
    manager = request.user.manager
    skills = LaborType.objects.filter(company=manager.company)
    if request.method == "POST":
        if 'delete_id' in request.POST:
            # check all events for labor requirements using this skill
            if LaborRequirement.objects.filter(labor_type__id=request.POST.get('delete_id')).exists():
                messages.error(request, "Cannot delete skill that is in use.")
                return redirect('view_skills')
            skill_id = request.POST.get('delete_id')
            skill = get_object_or_404(LaborType, id=skill_id, company=manager.company)
            skill.delete()
            messages.success(request, f"{skill.name} deleted")
            return redirect('view_skills')
        elif 'edit_id' in request.POST:
            skill_id = request.POST.get('edit_id')
            skill = get_object_or_404(LaborType, id=skill_id, company=manager.company)
            form = SkillForm(request.POST, instance=skill)
            if form.is_valid():
                form.save()
                return redirect('view_skills')
        elif 'add_skill' in request.POST:
            form = SkillForm(request.POST)
            if form.is_valid():
                skill = form.save(commit=False)
                skill.name = skill.name.title()
                if skill.name not in skills.values_list('name', flat=True):
                    skill.company = manager.company
                    skill.save()
                    messages.success(request, f"Skill {skill.name} added successfully.")
                    return redirect('view_skills')
                else:
                    messages.error(request, "Skill already exists.")
                    return redirect('view_skills')
    edit_forms = {skill.id: SkillForm(instance=skill) for skill in skills}
    add_form = SkillForm()
    context = {
        'skills': skills,
        'edit_forms': edit_forms,
        'add_form': add_form,
    }
    return render(request, 'callManager/view_skills.html', context)


@login_required
def view_workers(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    workers = Worker.objects.filter(companies=company).order_by('name')
    search_query = request.GET.get('search', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    if search_query or skill_id:
        query = Q()
        if search_query:
            query &= Q(name__icontains=search_query) | Q(phone_number__icontains=search_query)
        if skill_id:
            query &= Q(labor_types__id=skill_id)
        workers = workers.filter(query)
    paginator = Paginator(workers, int(request.GET.get('per_page', manager.per_page_preference)))
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    if request.method == "POST":
        if 'add_worker' in request.POST:
            form = WorkerForm(request.POST, company=manager.company)
            if form.is_valid():
                if Worker.objects.filter(phone_number=form.cleaned_data['phone_number'], companies=manager.company).exists():
                    messages.error(request, "Worker with this phone number already exists.")
                    return redirect('view_workers')
                worker = form.save(commit=False)
                if worker.phone_number.startswith('1') and len(worker.phone_number) == 11:
                    worker.phone_number = f"+{worker.phone_number}"
                elif not worker.phone_number.startswith('+') and len(worker.phone_number) == 10:
                    worker.phone_number = f"+1{worker.phone_number}"
                worker.save()
                worker.add_company(manager.company)
                messages.success(request, f"Worker {worker.name} added successfully.")
                query_params = {}
                if page_number != '1':
                    query_params['page'] = page_number
                if search_query:
                    query_params['search'] = search_query
                if skill_id:
                    query_params['skill'] = skill_id
                redirect_url = reverse('view_workers')
                if query_params:
                    redirect_url += '?' + urlencode(query_params)
                return redirect(redirect_url)
            else:
                messages.error(request, "Failed to add worker. Please check the form errors.")
    form = WorkerForm(company=manager.company)
    labor_types = LaborType.objects.filter(company=manager.company)
    context = {
        'workers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'skill_id': skill_id,
        'add_form': form,
        'labor_types': labor_types}
    return render(request, 'callManager/view_workers.html', context)


@login_required
def delete_worker(request, slug):
    if request.method == "DELETE":
        worker = get_object_or_404(Worker, slug=slug)
        worker_name = worker.name or "Unnamed Worker"
        labor_requests = LaborRequest.objects.filter(worker=worker)
        if labor_requests:
            messages.error(request, "Worker has labor requests and cannot be deleted.")
        else:
            worker.delete()
            messages.success(request, f"{worker_name} deleted.")
        return render(request, "callManager/messages_partial.html")


@login_required
def search_workers(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    workers = Worker.objects.filter(companies=manager.company).distinct().order_by('name')
    search_query = request.GET.get('search', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    if search_query or skill_id:
        query = Q()
        if search_query:
            query &= Q(name__icontains=search_query) | Q(phone_number__icontains=search_query)
        if skill_id:
            query &= Q(labor_types__id=skill_id)
        workers = workers.filter(query)
    per_page = request.GET.get('per_page', '')
    if not per_page or not per_page.isdigit():
        per_page = manager.per_page_preference
    else:
        per_page = int(per_page)
    paginator = Paginator(workers, per_page)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    context = {
        'workers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'skill_id': skill_id,
        'per_page': per_page,
        }
    return render(request, 'callManager/workers_list_partial.html', context)


@login_required
def edit_worker(request, worker_id):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    worker = get_object_or_404(Worker, id=worker_id)
    if request.method == "POST":
        form = WorkerForm(request.POST, instance=worker, company=manager.company)
        if form.is_valid():
            form.save()
            return redirect('view_workers')
    else:
        form = WorkerForm(instance=worker, company=manager.company)
    context = {
        'form': form,
        'worker': worker,
    }
    return render(request, 'callManager/edit_worker.html', context)


@login_required
def increment_nocallnoshow(request, worker_id):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    worker = get_object_or_404(Worker, id=worker_id)
    worker.nocallnoshow += 1
    worker.save()
    form = WorkerForm(instance=worker, company=request.user.manager.company)
    context = {
        'form': form,
        'worker': worker,
    }
    return render(request, 'callManager/nocallnoshow_partial.html', context)


@login_required
def decrement_nocallnoshow(request, worker_id):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    worker = get_object_or_404(Worker, id=worker_id)
    if worker.nocallnoshow > 0:  # Prevent negative values
        worker.nocallnoshow -= 1
        worker.save()
    form = WorkerForm(instance=worker, company=request.user.manager.company)
    context = {
        'form': form,
        'worker': worker,
    }
    return render(request, 'callManager/nocallnoshow_partial.html', context)


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
                                f"{company.name}: {call_time.event.event_name} {call_time.name} time changed. "
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


@login_required
def delete_call_time(request, slug):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    if request.method == "POST":
        call_time.delete()
        return redirect('event_detail', slug=call_time.event.slug)
    return redirect('event_detail', slug=call_time.event.slug)  # Fallback for GET


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


@csrf_exempt
def sms_webhook(request):
    if request.method == "POST":
        from_number = request.POST.get('From')
        body = request.POST.get('Body', '').strip().lower()
        try:
            worker = Worker.objects.get(phone_number=from_number)
            if 'yes' in body:
                worker.sms_consent = True
                worker.stop_sms = False
                worker.save()
                queued_requests = LaborRequest.objects.filter(worker=worker, requested=True, sms_sent=False).select_related('labor_requirement__call_time__event')
                if queued_requests.exists():
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                    # Group requests by event
                    events_to_notify = {}
                    for req in queued_requests:
                        event = req.labor_requirement.call_time.event
                        if event.slug not in events_to_notify:
                            events_to_notify[event.slug] = {'event': event, 'requests': []}
                        events_to_notify[event.slug]['requests'].append(req)
                    # Send one message per event
                    for event_slug, data in events_to_notify.items():
                        event = data['event']
                        company = event.company
                        log_sms(company)
                        requests = data['requests']
                        token = str(uuid.uuid4())  # Unique token per event
                        confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                        message_body = (
                                f"call confirmation: {event.event_name} "
                            f"on {event.start_date}: {confirmation_url}"
                        )
                        client.messages.create(body=message_body, from_=settings.TWILIO_PHONE_NUMBER, to=str(worker.phone_number))
                        # Update all requests for this event with the same token
                        for req in requests:
                            req.sms_sent = True
                            req.event_token = token
                            req.save()
                response = MessagingResponse()
                response.message("Thank you! You’ll now receive job requests.")
            elif 'no' in body:
                worker.sms_consent = False
                worker.save()
                response = MessagingResponse()
                response.message("You’ve opted out of job request messages.")
            elif 'stop' in body:
                worker.sms_consent = False
                worker.stop_sms = True
                company = worker.companies.first()
                worker.save()
                response = MessagingResponse()
                response.message("You’ve been unsubscribed from CallMan messages. Reply 'START' to resume.")
            elif 'start' in body:
                worker.sms_consent = True
                worker.stop_sms = False
                worker.save()
                queued_requests = LaborRequest.objects.filter(worker=worker, requested=True, sms_sent=False).select_related('labor_requirement__call_time__event')
                if queued_requests.exists():
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                    # Group requests by event
                    events_to_notify = {}
                    for req in queued_requests:
                        event = req.labor_requirement.call_time.event
                        if event.slug not in events_to_notify:
                            events_to_notify[event.slug] = {'event': event, 'requests': []}
                        events_to_notify[event.slug]['requests'].append(req)
                    # Send one message per event
                    for event_slug, data in events_to_notify.items():
                        event = data['event']
                        requests = data['requests']
                        token = str(uuid.uuid4())  # Unique token per event
                        confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                        message_body = (
                            f"call confirmation:  {event.event_name} "
                            f"on {event.start_date}: {confirmation_url}"
                        )
                        client.messages.create(body=message_body, from_=settings.TWILIO_PHONE_NUMBER, to=str(worker.phone_number))
                        # Update all requests for this event with the same token
                        for req in requests:
                            req.sms_sent = True
                            req.event_token = token
                            req.save()
                response = MessagingResponse()
                response.message("Welcome back! You’ll now receive job requests.")
            else:
                response = MessagingResponse()
                response.message("Please reply 'Yes' to consent, 'No' to opt out, or 'STOP' to unsubscribe.")
        except Worker.DoesNotExist:
            response = MessagingResponse()
            response.message("Number not recognized. Please contact support.")
        return HttpResponse(str(response), content_type='text/xml')
    return HttpResponse(status=400)


@csrf_exempt
def sms_reply_webhook(request):
    if request.method == "POST":
        from_number = request.POST.get('From')
        body = request.POST.get('Body', '').strip().upper()
        if len(body) >= 4 and body[0] in ['Y', 'N'] and body[1].isdigit():
            response = body[0]  # Y or N
            short_id = body[1:4]  # Next 3 chars
            labor_request = LaborRequest.objects.filter(
                worker__phone_number=from_number,
                token__startswith=short_id,  # Match first 3 chars of token
                sms_sent=True
            ).order_by('-requested_at').first()
            if labor_request:
                labor_request.response = 'yes' if response == 'Y' else 'no'
                labor_request.responded_at = timezone.now()
                labor_request.save()
                return HttpResponse("Response recorded", content_type="text/plain")
            else:
                return HttpResponse("No matching request found.", content_type="text/plain")
        else:
            return HttpResponse("Invalid format. Reply Y<3-digit-id> or N<3-digit-id>.", content_type="text/plain")
    return HttpResponse("Invalid request method", status=400, content_type="text/plain")


@login_required
def import_workers(request):
    user_agent = parse(request.META.get('HTTP_USER_AGENT', ''))
    manager = request.user.manager
    is_mobile = user_agent.is_mobile or user_agent.is_tablet
    qr_url = None
    if not is_mobile:
        token = OneTimeLoginToken.objects.create(
                user=request.user,
                expires_at=timezone.now() + timedelta(hours=1)
                )
        qr_url = request.build_absolute_uri(reverse('auto_login', args=[str(token.token)]))
    if request.method == "POST":
        form = WorkerImportForm(request.POST, request.FILES)
        if form.is_valid():
            vcf_file = TextIOWrapper(request.FILES['file'].file, encoding='utf-8')
            imported = 0
            errors = 0
            current_name = None
            current_phone = None
            for i, line in enumerate(vcf_file):
                line = line.strip()
                try:
                    if line.startswith('END:VCARD'):
                        if current_name or current_phone:
                            if current_phone:
                                current_phone = current_phone.replace(' ', '').replace('-', '')
                                if current_phone.startswith('1') and len(current_phone) == 11:
                                    current_phone = f"+{current_phone}"
                                elif not current_phone.startswith('+') and len(current_phone) == 10:
                                    current_phone = f"+1{current_phone}"
                                elif len(current_phone) < 10:
                                    messages.error(request, f"Invalid phone number: {current_phone}")
                                    continue
                            worker, created = Worker.objects.get_or_create(
                                phone_number=current_phone,
                                defaults={'name': current_name.strip() if current_name else None})
                            if created:
                                worker.add_company(manager.company)
                                imported += 1
                        current_name = None
                        current_phone = None
                    elif line.startswith('FN:'):
                        current_name = line[3:].strip()
                    elif line.startswith('TEL'):
                        parts = line.split(':')
                        if len(parts) > 1:
                            current_phone = parts[-1].strip()
                except Exception:
                    error_msg = f"Failed to import: {current_name or 'Unnamed'}, {current_phone or 'No phone'}"
                    messages.error(request, error_msg)
                    errors += 1
            messages.success(request, f"Imported {imported} workers.")
            if errors:
                messages.warning(request, f"Encountered {errors} import errors.")
            return render(request, 'callManager/import_workers.html', {'form': form, 'qr_url': qr_url, 'is_mobile': is_mobile})
    else:
        form = WorkerImportForm()
    return render(request, 'callManager/import_workers.html', {'form': form, 'qr_url': qr_url, 'is_mobile': is_mobile})


def confirm_event_requests(request, slug, event_token):
    event = get_object_or_404(Event, slug=slug)
    company = event.company
    first_request = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        event_token=event_token,
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
        location = quote(event.location_profile.name or "TBD")
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
            response_key = f"response_{labor_request.id}"
            response = request.POST.get(response_key)
            if response in ['yes', 'no']:
                labor_request.availability_response = response
                labor_request.responded_at = timezone.now()
                labor_request.save()
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                if response == 'yes' and labor_request.labor_requirement.fcfs_positions > 0 and not labor_request.is_reserved:
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


def user_registration(request):
    phone_number = request.GET.get('phone', '')
    if request.method == "POST":
        form = WorkerRegistrationForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            workers = Worker.objects.filter(phone_number=phone_number)
            if not workers.exists():
                messages.error(request, "No workers found with this phone number.")
                return render(request, 'callManager/user_registration.html', {'form': form, 'phone_number': phone_number})
            already_registered = workers.filter(user__isnull=False)
            if already_registered.exists():
                messages.error(request, "One or more workers with this phone number are already registered with a user account.")
                return render(request, 'callManager/user_registration.html', {'form': form, 'phone_number': phone_number})
            user = form.save()
            workers.update(user=user)
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, "Registration successful. You are now a worker.")
            return redirect('user_profile')
    else:
        form = WorkerRegistrationForm(initial={'phone_number': phone_number})
    context = {'form': form, 'phone_number': phone_number}
    return render(request, 'callManager/user_registration.html', context)


def registration_success(request):
    return render(request, 'callManager/registration_success.html')


@login_required
def labor_request_list(request, slug):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    event = labor_requirement.call_time.event
    company = event.company
    if request.method == "POST":
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
                        message_body = (
                                f"confirmed {labor_request.labor_requirement.labor_type}"
                                f" for {event.event_name} - {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d')}"
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
                        'event_token': uuid.uuid4()
                    }
                )
                if labor_requirement.labor_type not in worker.labor_types.all():
                    worker.labor_types.add(labor_requirement.labor_type)
                if not created and not labor_request.sms_sent:
                    labor_request.requested = True
                    labor_request.is_reserved = is_reserved
                    labor_request.event_token = uuid.uuid4()
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
        workers = Worker.objects.filter(companies=company).distinct()
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
    workers = Worker.objects.filter(companies=company).distinct()
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
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    workers = Worker.objects.filter(companies=manager.company).distinct()
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
def call_time_request_list(request, slug):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        requested=True
    ).select_related('worker', 'labor_requirement__labor_type')
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
                was_ncns = labor_request.response == 'ncns'
                if action == 'confirm':
                    call_time = labor_request.labor_requirement.call_time
                    if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                        message_body = (
                                f"confirmed {labor_request.labor_requirement.labor_type}"
                                f" for {event.event_name} - {call_time.name} at {call_time.time.strftime('%I:%M %p')} on {call_time.date.strftime('%B %d')}"
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
    confirmed_requests = labor_requests.filter(confirmed=True)
    declined_requests = labor_requests.filter(availability_response='no')
    ncns_requests = labor_requests.filter(availability_response='ncns')
    labor_types = LaborType.objects.filter(laborrequirement__call_time=call_time).distinct()
    message = request.GET.get('message', '')
    context = {
        'call_time': call_time,
        'pending_requests': pending_requests,
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
    manager = request.user.manager
    company = manager.company
    minimum_hours = labor_requirement.minimum_hours or call_time.minimum_hours or event.location_profile.minimum_hours or company.minimum_hours
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
        worker = labor_request.worker
        if action in ['sign_in', 'sign_out', 'ncns', 'call_out', 'update_start_time', 'update_end_time', 'add_meal_break', 'update_meal_break']:
            time_entry, created = TimeEntry.objects.get_or_create(
                labor_request=labor_request,
                worker=worker,
                call_time=call_time,
                defaults={'start_time': datetime.combine(call_time.date, call_time.time)})
            was_ncns = worker.nocallnoshow > 0 and labor_request.availability_response == 'no'
            if action == 'sign_in' and not time_entry.start_time:
                now = datetime.now()
                time_entry.start_time = now
                time_entry.save()
                messages.success(request, f"Signed in {worker.name}")
            elif action == 'sign_out' and time_entry.start_time and not time_entry.end_time:
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
def delete_meal_break(request, meal_break_id):
    meal_break = get_object_or_404(MealBreak, id=meal_break_id)
    meal_break.delete()
    if request.headers.get('HX-Request'):
        print("Deleted meal break")
    return HttpResponse("")

@login_required
def call_time_report(request, slug):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        confirmed=True).select_related('worker', 'labor_requirement__labor_type')
    labor_type_filter = request.GET.get('labor_type', 'All')
    if labor_type_filter != 'All':
        labor_requests = labor_requests.filter(labor_requirement__labor_type__id=labor_type_filter)
    confirmed_requests = labor_requests
    labor_types = LaborType.objects.filter(laborrequirement__call_time=call_time).distinct()
    format_type = request.GET.get('format', 'html')
    if format_type == 'pdf':
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph(f"Event: {call_time.event.event_name}", styles['Heading1']))
        elements.append(Paragraph(f"Call Time: {call_time.name} at {call_time.time} on {call_time.date}", styles['Heading2']))
        data = [['Name', 'Labor Type', 'Sign In', 'Sign Out', 'Meal Breaks', 'Normal Hours', 'Meal Penalty Hours', 'Total Hours']]
        for req in confirmed_requests:
            time_entry = req.time_entries.first()
            if time_entry and time_entry.meal_breaks.exists():
                paid_count = time_entry.meal_breaks.filter(break_type='paid').count()
                unpaid_count = time_entry.meal_breaks.filter(break_type='unpaid').count()
                meal_breaks = f"{paid_count} Paid, {unpaid_count} Unpaid"
                if paid_count == 0 and unpaid_count == 0:
                    meal_breaks = "None"
            else:
                meal_breaks = "None"
            row = [
                req.worker.name or "Unnamed Worker",
                req.labor_requirement.labor_type.name,
                time_entry.start_time.strftime('%I:%M %p') if time_entry and time_entry.start_time else "-",
                time_entry.end_time.strftime('%I:%M %p') if time_entry and time_entry.end_time else "-",
                meal_breaks,
                f"{time_entry.normal_hours:.2f}" if time_entry else "0.00",
                f"{time_entry.meal_penalty_hours:.2f}" if time_entry else "0.00",
                f"{time_entry.total_hours_worked:.2f}" if time_entry else "0.00"]
            data.append(row)
        table = Table(data, colWidths=[100, 80, 80, 80, 120, 60, 80, 60])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)]))
        elements.append(table)
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=30, bottomMargin=30)
        doc.build(elements)
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=f"call_time_report_{slug}.pdf")
    context = {
        'call_time': call_time,
        'confirmed_requests': confirmed_requests,
        'labor_types': labor_types,
        'selected_labor_type': labor_type_filter}
    return render(request, 'callManager/call_time_report.html', context)


class CustomLoginView(LoginView):
    template_name = 'callManager/login.html'
    
    def get_success_url(self):
        user = self.request.user
        if hasattr(user, 'steward'):
            return reverse('steward_dashboard')
        elif hasattr(user, 'manager'):
            return reverse('manager_dashboard')
        else:
            return reverse('index')


@login_required
def sms_usage_report(request):
    manager = request.user.manager
    daily_counts = SentSMS.objects.filter(
        company=manager.company).annotate(
        date=TruncDate('datetime_sent')).values(
        'company__name', 'date').annotate(
        count=Count('id')).order_by(
        'company__name', '-date')
    monthly_counts = SentSMS.objects.filter(
        company=manager.company).annotate(
        month=TruncMonth('datetime_sent')).values(
        'company__name', 'month').annotate(
        count=Count('id')).order_by(
        'company__name', '-month')
    monthly_daily_data = {}
    monthly_counts_with_keys = []
    for month_entry in monthly_counts:
        month = month_entry['month']
        key = month.strftime('%Y-%m')
        daily_data = SentSMS.objects.filter(
            company=manager.company,
            datetime_sent__year=month.year,
            datetime_sent__month=month.month).annotate(
            date=TruncDate('datetime_sent')).values(
            'date').annotate(
            count=Count('id')).order_by('date')
        monthly_daily_data[key] = [
            {'date': entry['date'].strftime('%Y-%m-%d'), 'count': entry['count']}
            for entry in daily_data]
        monthly_counts_with_keys.append({
            'company__name': month_entry['company__name'],
            'month': month,
            'count': month_entry['count'],
            'chart_key': key})
    context = {
        'daily_counts': daily_counts,
        'monthly_counts': monthly_counts_with_keys,
        'monthly_daily_data': monthly_daily_data,
        'company': manager.company}
    return render(request, 'callManager/sms_usage_report.html', context)


@login_required
def admin_sms_usage_report(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('login')
    daily_counts = SentSMS.objects.annotate(
        date=TruncDate('datetime_sent')).values(
        'company__name', 'date').annotate(
        count=Count('id')).order_by(
        'company__name', '-date')
    monthly_counts = SentSMS.objects.annotate(
        month=TruncMonth('datetime_sent')).values(
        'company__name', 'month').annotate(
        count=Count('id')).order_by(
        'company__name', '-month')
    monthly_daily_data = {}
    monthly_counts_with_keys = []
    for month_entry in monthly_counts:
        month = month_entry['month']
        company_name = month_entry['company__name']
        key = f"{company_name}_{month.strftime('%Y-%m')}"
        daily_data = SentSMS.objects.filter(
            company__name=company_name,
            datetime_sent__year=month.year,
            datetime_sent__month=month.month).annotate(
            date=TruncDate('datetime_sent')).values(
            'date').annotate(
            count=Count('id')).order_by('date')
        monthly_daily_data[key] = [
            {'date': entry['date'].strftime('%Y-%m-%d'), 'count': entry['count']}
            for entry in daily_data]
        monthly_counts_with_keys.append({
            'company__name': company_name,
            'month': month,
            'count': month_entry['count'],
            'chart_key': key})
    context = {
        'daily_counts': daily_counts,
        'monthly_counts': monthly_counts_with_keys,
        'monthly_daily_data': monthly_daily_data}
    return render(request, 'callManager/admin_sms_usage_report.html', context)


@login_required
def send_clock_in_link(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    confirmed_workers = Worker.objects.filter(
        labor_requests__labor_requirement__call_time__event=event,
        labor_requests__confirmed=True).distinct()
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
    sms_errors = []
    for worker in confirmed_workers:
        token, created = ClockInToken.objects.get_or_create(
            event=event,
            worker=worker,
            defaults={'expires_at': timezone.now() + timedelta(days=1), 'qr_sent': False})
        if token.qr_sent:
            continue
        qr_code_url = request.build_absolute_uri(reverse('display_qr_code', args=[event.slug, worker.slug]))
        if worker.sms_consent and not worker.stop_sms and worker.phone_number:
            message_body = (
                f"{manager.company.name}: Your clock-in QR code for {event.event_name}. "
                f"View: {qr_code_url}")
            if settings.TWILIO_ENABLED == 'enabled' and client:
                try:
                    client.messages.create(
                        body=message_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=str(worker.phone_number))
                    token.qr_sent = True
                    token.save()
                    log_sms(manager.company)
                except TwilioRestException as e:
                    sms_errors.append(f"Failed to notify {worker.name}: {str(e)}")
            else:
                token.qr_sent = True
                token.save()
                log_sms(manager.company)
                print(message_body)
    if sms_errors:
        messages.warning(request, f"Some SMS failed: {', '.join(sms_errors)}")
    else:
        messages.success(request, "Clock-in QR code links sent to workers.")
    return redirect('event_detail', slug=event.slug)

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
def scan_qr_code(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    context = {'event': event}
    return render(request, 'callManager/scan_qr_code.html', context)

@login_required
def manager_display_qr_code(request, slug, worker_slug):
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


def owner_dashboard(request):
    if not hasattr(request.user, 'owner'):
        return redirect('login')
    owner = request.user.owner
    company = owner.company
    if request.method == "POST":
        if 'phone' in request.POST:
            phone = request.POST.get('phone')
            if phone:
                invitation = ManagerInvitation.objects.create(company=company)
                registration_url = request.build_absolute_uri(reverse('register_manager', args=[str(invitation.token)]))
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                message_body = f'You are invited to become a manager for {company.name}. Register: {registration_url}'
                if settings.TWILIO_ENABLED == 'enabled' and client:
                    try:
                        client.messages.create(
                            body=message_body,
                            from_=settings.TWILIO_PHONE_NUMBER,
                            to=phone)
                        log_sms(company)
                        messages.success(request, f"Invitation sent to {phone}.")
                    except TwilioRestException as e:
                        messages.error(request, f"Failed to send invitation: {str(e)}")
                else:
                    log_sms(company)
                    print(message_body)
                    messages.success(request, f"Invitation printed for {phone}.")
            else:
                messages.error(request, "Please provide a phone number.")
        else:
            form = CompanyForm(request.POST, instance=company)
            if form.is_valid():
                form.save()
                messages.success(request, "Company information updated successfully.")
            else:
                messages.error(request, "Failed to update company information.")
    form = CompanyForm(instance=company)
    context = {'form': form, 'company': company}
    return render(request, 'callManager/owner_dashboard.html', context)


def register_manager(request, token):
    invitation = get_object_or_404(ManagerInvitation, token=token, used=False)
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            Manager.objects.create(user=user, company=invitation.company)
            invitation.used = True
            invitation.save()
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, "Registration successful. You are now a manager.")
            return redirect('manager_dashboard')
    form = UserCreationForm()
    context = {'form': form, 'invitation': invitation}
    return render(request, 'callManager/register_manager.html', context)


@login_required
def steward_dashboard(request):
    if not hasattr(request.user, 'steward'):
        return redirect('login')
    steward = request.user.steward
    events = Event.objects.filter(steward=steward).order_by('start_date')
    context = {'events': events}
    return render(request, 'callManager/steward_dashboard.html', context)


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

def signin_station(request, token):
    scanner = get_object_or_404(TemporaryScanner, token=token, expires_at__gt=timezone.now())
    user = scanner.user
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return render(request, 'callManager/signin_scanner.html', {'event': scanner.event})

@login_required
def location_profiles(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    profiles = LocationProfile.objects.filter(company=company)
    context = {'profiles': profiles, 'company': company}
    return render(request, 'callManager/location_profiles.html', context)


@login_required
def create_location_profile(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    if request.method == "POST":
        form = LocationProfileForm(request.POST)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.company = company
            profile.save()
            messages.success(request, "Location profile created successfully.")
            return redirect('location_profiles')
        else:
            messages.error(request, "Failed to create location profile.")
    else:
        initial = {
            'minimum_hours': company.minimum_hours,
            'meal_penalty_trigger_time': company.meal_penalty_trigger_time,
            'hour_round_up': company.hour_round_up,
        }
        form = LocationProfileForm(initial=initial)
    context = {'form': form, 'company': company}
    return render(request, 'callManager/create_location_profile.html', context)


@login_required
def edit_location_profile(request, pk):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    profile = get_object_or_404(LocationProfile, pk=pk, company=company)
    if request.method == "POST":
        form = LocationProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Location profile updated successfully.")
            return redirect('location_profiles')
        else:
            messages.error(request, "Failed to update location profile.")
    else:
        form = LocationProfileForm(instance=profile)
    context = {'form': form, 'profile': profile, 'company': company}
    return render(request, 'callManager/edit_location_profile.html', context)


@login_required
def delete_location_profile(request, pk):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    profile = get_object_or_404(LocationProfile, pk=pk, company=company)
    if request.method == "POST":
        profile.delete()
        messages.success(request, f"Location profile '{profile.name}' deleted successfully.")
        return redirect('location_profiles')
    messages.error(request, "Invalid request method.")
    return redirect('location_profiles')


@login_required
def user_profile(request):
    workers = request.user.workers.all()
    if not workers.exists():
        messages.error(request, "You are not currently associated with any company accounts. Please contact your manager.")
        return redirect('login')
    labor_requests = LaborRequest.objects.filter(worker__user=request.user).select_related(
        'labor_requirement__call_time__event'
    ).order_by('labor_requirement__call_time__date')
    context = {'labor_requests': labor_requests, 'workers': workers}
    return render(request, 'callManager/user_profile.html', context)

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

def auto_login(request, token):
    try:
        login_token = OneTimeLoginToken.objects.get(
            token=token,
            expires_at__gt=timezone.now(),
            used=False
        )
        login_token.used = True
        login_token.save()
        login(request, login_token.user)
        return redirect('import_workers')
    except OneTimeLoginToken.DoesNotExist:
        messages.error(request, "Invalid or expired login token.")
        return redirect('login')
