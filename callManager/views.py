from django.shortcuts import render, get_object_or_404, redirect
from .models import CallTime, LaborRequest, Event, LaborRequirement, LaborType, Worker, TimeEntry, MealBreak, SentSMS 
from django.contrib.auth.decorators import login_required
from .forms import (
        CallTimeForm,
        LaborTypeForm,
        LaborRequirementForm,
        EventForm,
        WorkerForm,
        WorkerImportForm,
        WorkerRegistrationForm,
        SkillForm,
        )
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, time, timedelta
from twilio.rest import Client
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from io import TextIOWrapper
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import uuid
from django.urls import reverse
from urllib.parse import urlencode, quote
from django.contrib import messages
import pytz
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Table, TableStyle, Paragraph, SimpleDocTemplate
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from django.http import FileResponse
from django.db.models.functions import TruncDate, TruncMonth

def log_sms(company):
    sms = SentSMS.objects.create(company=company)
    sms.save()

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
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    call_times = event.call_times.all().order_by('date', 'time')
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
        company = request.user.manager.company
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
                        message_body = f"CallMan: Confirm your calls for {event.event_name}: {confirmation_url}"
                        if settings.TWILIO_ENABLED == 'enabled' and client:
                            try:
                                client.messages.create(
                                    body=message_body,
                                    from_=settings.TWILIO_PHONE_NUMBER,
                                    to=str(worker.phone_number)
                                )
                                print(f"Sent SMS to {worker.phone_number} with token {token}")
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
        context = {'event': event, 'call_times': call_times, 'labor_counts': labor_counts, 'message': message}
        return render(request, 'callManager/event_detail.html', context)
    context = {
        'event': event,
        'call_times': call_times,
        'labor_counts': labor_counts
    }
    return render(request, 'callManager/event_detail.html', context)


@login_required
def edit_event(request, slug):
    manager = request.user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    if request.method == "POST":
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            return redirect('manager_dashboard')
    else:
        form = EventForm(instance=event)
    context = {
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


from django.utils import timezone
from datetime import datetime
@login_required
def manager_dashboard(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    events = Event.objects.filter(company=company).order_by('-start_date')
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
        confirmed_count=Count('laborrequest', filter=Q(laborrequest__confirmed=True)))
    unfilled_spots = sum(max(0, lr.needed_labor - lr.confirmed_count) for lr in labor_requirements)
    current_date = timezone.now()
    start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_of_month + timedelta(days=32)).replace(day=1)
    sent_messages = SentSMS.objects.filter(
        company=company,
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
    context = {
        'company': company,
        'events': events,
        'total_events': total_events,
        'pending_requests': pending_requests,
        'sent_messages': sent_messages,
        'declined': declined_requests,
        'unfilled_spots': unfilled_spots,
        'event_labor_needs': event_labor_needs}
    return render(request, 'callManager/manager_dashboard.html', context)


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
        form = LaborRequirementForm(request.POST, company=manager.company)
        if form.is_valid():
            labor_requirement = form.save(commit=False)
            labor_requirement.call_time = call_time
            # Check for existing LaborRequirement
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
        form = LaborRequirementForm(company=manager.company)
    
    context = {'form': form, 'call_time': call_time}
    return render(request, 'callManager/add_labor_to_call.html', context)


@login_required
def create_event(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.company = manager.company
            event.save()  # Slug generated via save()
            return redirect('event_detail', slug=event.slug)  # Use slug instead of event_id
    else:
        form = EventForm()
    context = {'form': form}
    return render(request, 'callManager/create_event.html', context)


@login_required
def view_skills(request):
    manager = request.user.manager
    skills = LaborType.objects.filter(company=manager.company)
    if request.method == "POST":
        if 'delete_id' in request.POST:
            skill_id = request.POST.get('delete_id')
            skill = get_object_or_404(LaborType, id=skill_id, company=manager.company)
            skill.delete()
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
                skill.company = manager.company
                skill.save()
                return redirect('view_skills')
    # GET request: show all skills and forms
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
    workers = Worker.objects.all().order_by('name')
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers = workers.filter(
            Q(name__icontains=search_query) |
            Q(phone_number__icontains=search_query)
        )
    paginator = Paginator(workers, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    if request.method == "POST":
        if 'delete_id' in request.POST:
            worker_id = request.POST.get('delete_id')
            worker = get_object_or_404(Worker, id=worker_id)
            worker.delete()
            # Preserve page and search in redirect
            query_params = {}
            if page_number != '1':  # Only include page if not 1
                query_params['page'] = page_number
            if search_query:
                query_params['search'] = search_query
            redirect_url = reverse('view_workers')  # Base URL
            if query_params:
                redirect_url += '?' + urlencode(query_params)  # Append query string
            return redirect(redirect_url)
        elif 'add_worker' in request.POST:
            form = WorkerForm(request.POST, company=manager.company)
            if form.is_valid():
                worker = form.save(commit=False)
                worker.save()
                worker.companies.add(manager.company)
                # Preserve page and search on add
                query_params = {}
                if page_number != '1':
                    query_params['page'] = page_number
                if search_query:
                    query_params['search'] = search_query
                redirect_url = reverse('view_workers')
                if query_params:
                    redirect_url += '?' + urlencode(query_params)
                return redirect(redirect_url)
    add_form = WorkerForm(company=manager.company)
    context = {
        'workers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'add_form': add_form,
    }
    return render(request, 'callManager/view_workers.html', context)


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
                    sms_sent=True
                ).select_related('worker')
                if confirmed_requests:
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                    sms_errors = []
                    for req in confirmed_requests:
                        worker = req.worker
                        if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                            message_body = (
                                f"{company.name}: {call_time.event.event_name} {call_time.name} time changed. "
                                f"Now: {updated_call_time.date.strftime('%B %d')} at {updated_call_time.time.strftime('%I:%M %p')}."
                            )
                            if settings.TWILIO_ENABLED == 'enabled' and client:
                                try:
                                    client.messages.create(
                                        body=message_body,
                                        from_=settings.TWILIO_PHONE_NUMBER,
                                        to=str(worker.phone_number))
                                    print(f"Sent change notification to {worker.phone_number}")
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
            log_sms(worker.companies.first())
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
    manager = request.user.manager
    if request.method == "POST":
        form = WorkerImportForm(request.POST, request.FILES)
        if form.is_valid():
            vcf_file = TextIOWrapper(request.FILES['file'].file, encoding='utf-8')
            imported = 0
            errors = []
            current_name = None
            current_phone = None
            for i, line in enumerate(vcf_file):
                line = line.strip()
                try:
                    if line.startswith('END:VCARD'):
                        if current_name or current_phone:
                            # Normalize phone number to E.164
                            if current_phone:
                                current_phone = current_phone.replace(' ', '').replace('-', '')
                                if current_phone.startswith('1') and len(current_phone) == 11:
                                    current_phone = f"+{current_phone}"
                                elif not current_phone.startswith('+') and len(current_phone) == 10:
                                    current_phone = f"+1{current_phone}"
                            worker, created = Worker.objects.get_or_create(
                                phone_number=current_phone,
                                defaults={'name': current_name.strip() if current_name else None}
                            )
                            if created:
                                imported += 1
                        current_name = None
                        current_phone = None
                    elif line.startswith('FN:'):
                        current_name = line[3:].strip()
                    elif line.startswith('TEL'):
                        # Extract phone from TEL line (e.g., TEL;TYPE=CELL:+1234567890)
                        parts = line.split(':')
                        if len(parts) > 1:
                            current_phone = parts[-1].strip()
                except Exception as e:
                    errors.append(f"Error at line {i + 1}: {str(e)} (Line: {line[:50]})")
            message = f"Imported {imported} workers."
            if errors:
                message += f" Errors: {', '.join(errors[:5])}" + (f" and {len(errors) - 5} more" if len(errors) > 5 else "")
            return render(request, 'callManager/import_workers.html', {'form': form, 'message': message})
    else:
        form = WorkerImportForm()
    return render(request, 'callManager/import_workers.html', {'form': form})


@login_required
def confirm_event_requests(request, slug, event_token):
    event = get_object_or_404(Event, slug=slug)
    first_request = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        event_token=event_token,
        worker__phone_number__isnull=False
    ).select_related('worker').first()
    if not first_request:
        context = {'message': 'No requests found for this link.'}
        return render(request, 'callManager/confirm_error.html', context)
    worker_phone = first_request.worker.phone_number
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        requested=True,
        availability_response__isnull=True,
        worker__phone_number=worker_phone
    ).select_related(
        'labor_requirement__call_time',
        'labor_requirement__labor_type'
    ).annotate(
        confirmed_count=Count('labor_requirement__laborrequest', filter=Q(labor_requirement__laborrequest__confirmed=True))
    ).order_by(
        'labor_requirement__call_time__date',
        'labor_requirement__call_time__time')
    confirmed_call_times = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        confirmed=True,
        worker__phone_number=worker_phone
    ).select_related(
        'labor_requirement__call_time',
        'labor_requirement__labor_type'
    ).order_by(
        'labor_requirement__call_time__date',
        'labor_requirement__call_time__time')
    registration_url = request.build_absolute_uri(f"/worker/register/?phone={worker_phone}")
    calendar_links = []
    for req in confirmed_call_times:
        call_time = req.labor_requirement.call_time
        start_dt = datetime.combine(call_time.date, call_time.time)
        end_dt = start_dt + timedelta(hours=4)
        event_name = quote(f"{event.event_name} - {call_time.name}")
        location = quote(event.event_location or "TBD")
        details = quote(f"Position: {req.labor_requirement.labor_type.name}\nConfirmed for {first_request.worker.name}")
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
    if request.method == "POST":
        for labor_request in labor_requests:
            response_key = f"response_{labor_request.id}"
            response = request.POST.get(response_key)
            if response in ['yes', 'no']:
                labor_request.availability_response = response
                labor_request.responded_at = timezone.now()
                labor_request.save()
                if response == 'yes' and labor_request.labor_requirement.fcfs_positions > 0 and not labor_request.is_reserved:
                    confirmed_count = LaborRequest.objects.filter(
                        labor_requirement=labor_request.labor_requirement,
                        confirmed=True).count()
                    if confirmed_count < labor_request.labor_requirement.fcfs_positions:
                        labor_request.confirmed = True
                        labor_request.save()
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
                            is_reserved=False
                        ).exclude(id=labor_request.id).order_by('responded_at').first()
                        if available_fcfs:
                            available_fcfs.confirmed = True
                            available_fcfs.save()
        context = {
            'event': event,
            'registration_url': registration_url,
            'confirmed_call_times': calendar_links}
        return render(request, 'callManager/confirm_success.html', context)
    context = {
        'event': event,
        'labor_requests': labor_requests,
        'registration_url': registration_url,
        'confirmed_call_times': calendar_links}
    if not labor_requests.exists() and not calendar_links:
        context['message'] = "No requests found for this link."
        return render(request, 'callManager/confirm_error.html', context)
    return render(request, 'callManager/confirm_event_requests.html', context)


def worker_registration(request):
    phone_number = request.GET.get('phone', '')
    if request.method == "POST":
        form = WorkerRegistrationForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            existing_worker = Worker.objects.filter(phone_number=phone_number).first()
            if existing_worker and existing_worker.user:
                # Update existing worker’s name and labor types if user exists
                existing_worker.name = form.cleaned_data['name']
                existing_worker.labor_types.set(form.cleaned_data['labor_types'])
                existing_worker.save()
                return redirect('registration_success')
            else:
                # Create new worker and user
                worker = form.save()
                return redirect('registration_success')
    else:
        form = WorkerRegistrationForm(initial={'phone_number': phone_number})
        form.fields['phone_number'].disabled = True
    context = {
        'form': form,
        'phone_number': phone_number,
    }
    return render(request, 'callManager/worker_registration.html', context)
def registration_success(request):
    return render(request, 'callManager/registration_success.html')


@login_required
def labor_request_list(request, slug):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    if request.method == "POST":
        if 'request_id' in request.POST:
            request_id = request.POST.get('request_id')
            action = request.POST.get('action')
            if request_id and action in ['confirm', 'decline', 'delete']:
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement=labor_requirement)
                worker = labor_request.worker
                if action == 'confirm':
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
                elif action == 'decline' and labor_request.availability_response is None:
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
        workers = Worker.objects.all().distinct()
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
    workers = Worker.objects.all().distinct()
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
    return render(request, 'callManager/labor_request_list.html', context)


@login_required
def fill_labor_request_list(request, slug):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement, requested=True).select_related('worker')
    workers = Worker.objects.all().distinct()
    workers_list = list(workers)
    workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers_list = [w for w in workers_list if search_query.lower() in (w.name or '').lower() or search_query in (w.phone_number or '')]
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
        requested=True
    ).filter(
        labor_requirement__call_time__date__gte=window_start.date(),
        labor_requirement__call_time__date__lte=window_end.date()
    ).filter(
        labor_requirement__call_time__time__gte=window_start.time() if window_start.date() == labor_requirement.call_time.date else '00:00:00',
        labor_requirement__call_time__time__lte=window_end.time() if window_end.date() == labor_requirement.call_time.date else '23:59:59'
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
    pending_requests = labor_requests.filter(availability_response__isnull=True)
    available_requests = labor_requests.filter(availability_response='yes', confirmed=False)
    confirmed_requests = labor_requests.filter(confirmed=True)
    print(f"confirmed_requests: {confirmed_requests.count()}")
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
        'per_page': per_page
    }
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
        if 'request_id' in request.POST:
            request_id = request.POST.get('request_id')
            action = request.POST.get('action')
            if request_id and action in ['confirm', 'decline', 'ncns', 'delete']:
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
                worker = labor_request.worker
                was_ncns = labor_request.response == 'ncns'
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
                minutes = end_time.minute
                if minutes > 35:
                    end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                elif minutes > 5:
                    end_time = end_time.replace(minute=30, second=0, microsecond=0)
                else:
                    end_time = end_time.replace(minute=0, second=0, microsecond=0)
                time_entry.end_time = end_time
                time_entry.save()
                print(f"Sign Out Time: {end_time}, Normal Hours: {time_entry.normal_hours}, Meal Penalty Hours: {time_entry.meal_penalty_hours}, Worker: {worker.name}")
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
                        print(f"Updated Meal Break: {new_time}, Type: {meal_break.break_type}, Normal Hours: {time_entry.normal_hours}, Meal Penalty Hours: {time_entry.meal_penalty_hours}, Worker: {worker.name}")
                        if request.headers.get('HX-Request'):
                            context = {'call_time': call_time, 'meal_break': meal_break}
                            return render(request, 'callManager/meal_break_display_partial.html', context)
                        messages.success(request, f"Updated meal break for {worker.name}")
                    else:
                        error_message = "Meal break time must be within the shift duration"
                        print(f"Meal Break Validation Failed: {time_str}, Date: {date_str}, Start: {time_entry.start_time}, End: {time_entry.end_time or datetime.now()}, Worker: {worker.name}")
                except (ValueError, TypeError) as e:
                    error_message = "Invalid date or time format for meal break"
                    print(f"Meal Break Update Error: {str(e)}, Time: {time_str}, Date: {date_str}, Worker: {worker.name}")
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
                    print(f"Updated Time: {new_time}, Action: {action}, Normal Hours: {time_entry.normal_hours}, Meal Penalty Hours: {time_entry.meal_penalty_hours}, Worker: {worker.name}")
                    if request.headers.get('HX-Request'):
                        context = {'call_time': call_time, 'labor_request': labor_request, 'field': action.replace('update_', '')}
                        return render(request, 'callManager/time_entry_display_partial.html', context)
                    messages.success(request, f"Updated {action.replace('update_', '')} for {worker.name}")
                except (ValueError, TypeError):
                    messages.error(request, f"Invalid date or time format")
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

@login_required
def sms_usage_report(request):
    manager = request.user.manager
    daily_counts = SentSMS.objects.filter(
        company=manager.company
    ).annotate(
        date=TruncDate('datetime_sent')
    ).values(
        'company__name', 'date'
    ).annotate(
        count=Count('id')
    ).order_by(
        'company__name', '-date')
    monthly_counts = SentSMS.objects.filter(
        company=manager.company
    ).annotate(
        month=TruncMonth('datetime_sent')
    ).values(
        'company__name', 'month'
    ).annotate(
        count=Count('id')
    ).order_by(
        'company__name', '-month')
    monthly_daily_data = {}
    for month_entry in monthly_counts:
        month = month_entry['month']
        daily_data = SentSMS.objects.filter(
            company=manager.company,
            datetime_sent__year=month.year,
            datetime_sent__month=month.month
        ).annotate(
            date=TruncDate('datetime_sent')
        ).values(
            'date'
        ).annotate(
            count=Count('id')
        ).order_by(
            'date')
        monthly_daily_data[month.strftime('%Y-%m')] = [
            {'date': entry['date'].strftime('%Y-%m-%d'), 'count': entry['count']}
            for entry in daily_data]
    context = {
        'daily_counts': daily_counts,
        'monthly_counts': monthly_counts,
        'monthly_daily_data': monthly_daily_data,
        'company': manager.company}
    return render(request, 'callManager/sms_usage_report.html', context)
