from django.shortcuts import render, get_object_or_404, redirect
from .models import CallTime, LaborRequest, Event, LaborRequirement, LaborType, Worker
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
from datetime import datetime, timedelta
from twilio.rest import Client
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from io import TextIOWrapper
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import uuid
from django.urls import reverse
from urllib.parse import urlencode
from django.contrib import messages


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
    call_times = event.call_times.all()
    labor_requirements = LaborRequirement.objects.filter(call_time__event=event)
    labor_requests = LaborRequest.objects.filter(labor_requirement__call_time__event=event).values('labor_requirement_id').annotate(pending_count=Count('id', filter=Q(requested=True) & Q(response__isnull=True)),confirmed_count=Count('id', filter=Q(response='yes')),rejected_count=Count('id', filter=Q(response='no')))
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
                display_text = f"{needed} filled, overbooked by {overbooked} pending"
        elif confirmed >= needed:
            display_text = f"{confirmed} filled"
        else:
            display_text = f"{needed} needed ({pending} pending, {confirmed} confirmed, {rejected} rejected)"
        labor_counts[lr_id] = {'pending': pending,'confirmed': confirmed,'rejected': rejected,'display_text': display_text,'labor_requirement': lr}
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
                                client.messages.create(body=consent_body, from_=settings.TWILIO_PHONE_NUMBER, to=str(worker.phone_number))
                                worker.sent_consent_msg = True
                                worker.save()
                            except TwilioRestException as e:
                                sms_errors.append(f"Consent SMS failed for {worker.name}: {str(e)}")
                        else:
                            worker.sent_consent_msg = True
                            worker.save()
                    elif worker.sms_consent:
                        token = worker_tokens.get(worker.id, str(uuid.uuid4()))
                        worker_tokens[worker.id] = token
                        confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
                        message_body = f"CallMan: Confirm your calls for {event.event_name}: {confirmation_url}"
                        if settings.TWILIO_ENABLED == 'enabled' and client:
                            try:
                                client.messages.create(body=message_body, from_=settings.TWILIO_PHONE_NUMBER, to=str(worker.phone_number))
                                print(f"Sent SMS to {worker.phone_number} with token {token}")
                            except TwilioRestException as e:
                                sms_errors.append(f"SMS failed for {worker.name}: {str(e)}")
                        else:
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
    context = {'event': event,'call_times': call_times,'labor_counts': labor_counts}
    return render(request, 'callManager/event_detail.html', context)


@login_required
def manager_dashboard(request):
    # Ensure the user is a manager
    if not hasattr(request.user, 'manager'):
        return redirect('login')  # Or a custom "access denied" page
    
    manager = request.user.manager
    company = manager.company
    events = Event.objects.filter(company=company).order_by('-start_date')
    total_events = events.count()
    labor_agg = LaborRequirement.objects.filter(call_time__event__company=company).aggregate(total=Sum('needed_labor'))
    total_labor_needed = labor_agg['total'] if labor_agg['total'] is not None else 0
    total_requests = LaborRequest.objects.filter(
            labor_requirement__call_time__event__company=company,
            response=None).count()
    confirmed_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        response='yes',
    ).count()
    declined_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        response='no',
    ).count()
    context = {
        'company': company,
        'events': events,
        'total_events': total_events,
        'total_labor_needed': total_labor_needed,
        'total_requests': total_requests,
        'confirmed_requests': confirmed_requests,
        'declined_requests': declined_requests,
    }
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
        response='no',
    ).select_related('worker', 'labor_requirement__call_time__event')
    context = {
        'requests': declined_requests,
    }
    return render(request, 'callManager/declined_requests.html', context)


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
def fill_labor_call(request, labor_requirement_id):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, id=labor_requirement_id, call_time__event__company=manager.company)
    worker_data = Worker.objects.values('id', 'name', 'phone_number').distinct()
    worker_ids = [w['id'] for w in worker_data]
    workers = Worker.objects.filter(id__in=worker_ids)
    workers_list = list(workers)
    workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers_list = [
            w for w in workers_list
            if search_query.lower() in (w.name or '').lower() or search_query in (w.phone_number or '')
        ]
    paginator = Paginator(workers_list, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    current_call_time = labor_requirement.call_time
    event_date = current_call_time.event.start_date
    current_datetime = datetime.combine(event_date, current_call_time.time)
    window_start = current_datetime - timedelta(hours=5)
    window_end = current_datetime + timedelta(hours=5)
    conflicting_requests = LaborRequest.objects.filter(
        worker__in=page_obj.object_list,
        labor_requirement__call_time__event__start_date=event_date,
        labor_requirement__call_time__time__gte=window_start.time(),
        labor_requirement__call_time__time__lte=window_end.time(),
        requested=True,
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    worker_conflicts = {}
    for labor_request in conflicting_requests:
        if labor_request.worker_id not in worker_conflicts:
            worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.response == 'yes' else 'Declined' if labor_request.response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id
        }
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.response == 'yes':
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True
    if request.method == "POST":
        worker_ids = request.POST.getlist('worker_ids')
        sms_errors = []
        for worker_id in worker_ids:
            worker = Worker.objects.get(id=worker_id)
            labor_request, created = LaborRequest.objects.get_or_create(
                worker=worker,
                labor_requirement=labor_requirement,
                defaults={'requested': True, 'sms_sent': False}
            )
            if labor_requirement.labor_type not in worker.labor_types.all():
                worker.labor_types.add(labor_requirement.labor_type)
            if not created and not labor_request.sms_sent:
                labor_request.requested = True
                labor_request.save()
        message = f"{len(worker_ids)} workers queued for request."
        context = {
            'labor_requirement': labor_requirement,
            'workers': page_obj,
            'worker_conflicts': worker_conflicts,
            'page_obj': page_obj,
            'search_query': search_query,
            'message': message,
        }
        return render(request, 'callManager/fill_labor_call_partial.html', context)
    context = {
        'labor_requirement': labor_requirement,
        'workers': page_obj,
        'worker_conflicts': worker_conflicts,
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'callManager/fill_labor_call.html', context)


@login_required
def fill_labor_call_list(request, labor_requirement_id):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, id=labor_requirement_id, call_time__event__company=manager.company)
    worker_data = Worker.objects.values('id', 'name', 'phone_number').distinct()
    worker_ids = [w['id'] for w in worker_data]
    workers = Worker.objects.filter(id__in=worker_ids)
    workers_list = list(workers)
    workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers_list = [
            w for w in workers_list
            if search_query.lower() in (w.name or '').lower() or search_query in (w.phone_number or '')
        ]
    paginator = Paginator(workers_list, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    current_call_time = labor_requirement.call_time
    event_date = current_call_time.event.start_date
    current_datetime = datetime.combine(event_date, current_call_time.time)
    window_start = current_datetime - timedelta(hours=5)
    window_end = current_datetime + timedelta(hours=5)
    conflicting_requests = LaborRequest.objects.filter(
        worker__in=page_obj.object_list,
        labor_requirement__call_time__event__start_date=event_date,
        labor_requirement__call_time__time__gte=window_start.time(),
        labor_requirement__call_time__time__lte=window_end.time(),
        requested=True,
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    worker_conflicts = {}
    for labor_request in conflicting_requests:
        if labor_request.worker_id not in worker_conflicts:
            worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.response == 'yes' else 'Declined' if labor_request.response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id
        }
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.response == 'yes':
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True
    context = {
        'labor_requirement': labor_requirement,
        'workers': page_obj,
        'worker_conflicts': worker_conflicts,
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'callManager/fill_labor_call_list_partial.html', context)


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
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    if request.method == "POST":
        form = CallTimeForm(request.POST, instance=call_time, event=call_time.event)
        if form.is_valid():
            updated_call_time = form.save(commit=False)
            if call_time.has_changed():  # Check before saving
                confirmed_requests = LaborRequest.objects.filter(
                    labor_requirement__call_time=call_time,
                    response__in=['yes', None],
                    sms_sent=True
                ).select_related('worker')
                if confirmed_requests:
                    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
                    sms_errors = []
                    for req in confirmed_requests:
                        worker = req.worker
                        if worker.sms_consent and not worker.stop_sms and worker.phone_number:
                            message_body = (
                                f"CallMan: Update to {call_time.name} for {call_time.event.event_name}. "
                                f"Old: {call_time.original_date} at {call_time.original_time}. "
                                f"New: {updated_call_time.date} at {updated_call_time.time}."
                            )
                            if settings.TWILIO_ENABLED == 'enabled' and client:
                                try:
                                    client.messages.create(
                                        body=message_body,
                                        from_=settings.TWILIO_PHONE_NUMBER,
                                        to=str(worker.phone_number)
                                    )
                                    print(f"Sent change notification to {worker.phone_number}")
                                except TwilioRestException as e:
                                    sms_errors.append(f"Failed to notify {worker.name}: {str(e)}")
                            else:
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


def confirm_event_requests(request, slug, event_token):
    event = get_object_or_404(Event, slug=slug)
    first_request = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        event_token=event_token,
        requested=True
    ).select_related('worker').first()
    if not first_request:
        context = {'message': "No pending requests found for this link."}
        return render(request, 'callManager/confirm_error.html', context)
    worker_phone = first_request.worker.phone_number
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        event_token=event_token,
        requested=True,
        response__isnull=True,
        worker__phone_number=worker_phone  # Filter by worker's phone
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    registration_url = request.build_absolute_uri(f"/worker/register/?phone={worker_phone}")
    if not labor_requests.exists():
        context = {'message': "No pending requests found for this link.",'registration_url': registration_url}
        return render(request, 'callManager/confirm_error.html', context)
    if request.method == "POST":
        for labor_request in labor_requests:
            response_key = f"response_{labor_request.id}"
            response = request.POST.get(response_key)
            if response in ['yes', 'no']:
                labor_request.response = response
                labor_request.responded_at = timezone.now()
                labor_request.save()
        confirmed_call_times = LaborRequest.objects.filter(
            response='yes'
            )
        context = {
            'event': event,
            'registration_url': registration_url,
            'confirmed_call_times': confirmed_call_times,
        }
        return render(request, 'callManager/confirm_success.html', context)
    context = {'event': event,'labor_requests': labor_requests,'registration_url': registration_url}
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
    labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement,requested=True).select_related('worker')
    message = None
    if request.method == "POST":
        if 'request_id' in request.POST:
            request_id = request.POST.get('request_id')
            action = request.POST.get('action')
            if request_id and action in ['confirm', 'decline']:
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement=labor_requirement)
                labor_request.response = 'yes' if action == 'confirm' else 'no'
                labor_request.responded_at = timezone.now()
                labor_request.sms_sent = True
                labor_request.save()
                message = f"Request {action}d successfully."
            elif request_id and action == 'delete':
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement=labor_requirement)
                labor_request.delete()
                message = "Request deleted successfully."
        elif 'worker_ids' in request.POST:
            worker_ids = request.POST.getlist('worker_ids')
            for worker_id in worker_ids:
                worker = Worker.objects.get(id=worker_id)
                labor_request, created = LaborRequest.objects.get_or_create(worker=worker,labor_requirement=labor_requirement,defaults={'requested': True, 'sms_sent': False})
                if labor_requirement.labor_type not in worker.labor_types.all():
                    worker.labor_types.add(labor_requirement.labor_type)
                if not created and not labor_request.sms_sent:
                    labor_request.requested = True
                    labor_request.save()
            message = f"{len(worker_ids)} workers queued for request."
            if request.headers.get('HX-Request'):
                pending_requests = labor_requests.filter(response__isnull=True)
                confirmed_requests = labor_requests.filter(response='yes')
                declined_requests = labor_requests.filter(response='no')
                context = {
                    'labor_requirement': labor_requirement,
                    'pending_requests': pending_requests,
                    'confirmed_requests': confirmed_requests,
                    'declined_requests': declined_requests,
                    'is_filled': labor_requirement.needed_labor <= confirmed_requests.count(),
                    'message': message,
                }
                return render(request, 'callManager/labor_request_content_partial.html', context)
        pending_requests = labor_requests.filter(response__isnull=True)
        confirmed_requests = labor_requests.filter(response='yes')
        declined_requests = labor_requests.filter(response='no')
        context = {
            'labor_requirement': labor_requirement,
            'pending_requests': pending_requests,
            'confirmed_requests': confirmed_requests,
            'declined_requests': declined_requests,
            'is_filled': labor_requirement.needed_labor <= confirmed_requests.count(),
            'message': message,
        }
        return render(request, 'callManager/labor_request_list.html', context)
    pending_requests = labor_requests.filter(response__isnull=True)
    confirmed_requests = labor_requests.filter(response='yes')
    declined_requests = labor_requests.filter(response='no')
    context = {
        'labor_requirement': labor_requirement,
        'pending_requests': pending_requests,
        'confirmed_requests': confirmed_requests,
        'declined_requests': declined_requests,
        'is_filled': labor_requirement.needed_labor <= confirmed_requests.count(),
    }
    return render(request, 'callManager/labor_request_list.html', context)


@login_required
def fill_labor_request_list(request, slug):
    manager = request.user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug, call_time__event__company=manager.company)
    worker_data = Worker.objects.values('id', 'name', 'phone_number').distinct()
    worker_ids = [w['id'] for w in worker_data]
    workers = Worker.objects.filter(id__in=worker_ids)
    workers_list = list(workers)
    workers_list.sort(key=lambda w: (labor_requirement.labor_type not in w.labor_types.all(), w.name or ''))
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers_list = [
            w for w in workers_list
            if search_query.lower() in (w.name or '').lower() or search_query in (w.phone_number or '')
        ]
    paginator = Paginator(workers_list, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    current_call_time = labor_requirement.call_time
    event_date = current_call_time.event.start_date
    current_datetime = datetime.combine(event_date, current_call_time.time)
    window_start = current_datetime - timedelta(hours=5)
    window_end = current_datetime + timedelta(hours=5)
    conflicting_requests = LaborRequest.objects.filter(
        worker__in=page_obj.object_list,
        labor_requirement__call_time__event__start_date=event_date,
        labor_requirement__call_time__time__gte=window_start.time(),
        labor_requirement__call_time__time__lte=window_end.time(),
        requested=True,
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')
    worker_conflicts = {}
    for labor_request in conflicting_requests:
        if labor_request.worker_id not in worker_conflicts:
            worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.response == 'yes' else 'Declined' if labor_request.response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id
        }
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.response == 'yes':
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True
    context = {
        'labor_requirement': labor_requirement,
        'workers': page_obj,
        'worker_conflicts': worker_conflicts,
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'callManager/fill_labor_request_list_partial.html', context)


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
            if request_id and action in ['confirm', 'decline']:
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
                labor_request.response = 'yes' if action == 'confirm' else 'no'
                labor_request.responded_at = timezone.now()
                labor_request.sms_sent = True
                labor_request.save()
                message = f"Request {action}d successfully."
            elif request_id and action == 'delete':
                labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
                labor_request.delete()
                message = "Request deleted successfully."
            return redirect('call_time_request_list', slug=slug)
    pending_requests = labor_requests.filter(response__isnull=True)
    confirmed_requests = labor_requests.filter(response='yes')
    declined_requests = labor_requests.filter(response='no')
    labor_types = LaborType.objects.filter(laborrequirement__call_time=call_time).distinct()
    context = {
        'call_time': call_time,
        'pending_requests': pending_requests,
        'confirmed_requests': confirmed_requests,
        'declined_requests': declined_requests,
        'labor_types': labor_types,
        'selected_labor_type': labor_type_filter,
    }
    return render(request, 'callManager/call_time_request_list.html', context)
