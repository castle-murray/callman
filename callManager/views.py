from django.shortcuts import render, get_object_or_404, redirect
from .models import CallTime, LaborRequest, Event, LaborRequirement, LaborType, Worker
from django.contrib.auth.decorators import login_required
from .forms import CallTimeForm, LaborTypeForm, LaborRequirementForm, EventForm, WorkerForm
from django.db.models import Sum, Q
from datetime import datetime, timedelta
from twilio.rest import Client
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone



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
def event_detail(request, event_id):
    manager = request.user.manager
    event = get_object_or_404(Event, id=event_id, company=manager.company)
    call_times = event.call_times.all()
    labor_requests = LaborRequest.objects.filter(labor_requirement__call_time__event=event)
    
    context = {
        'event': event,
        'call_times': call_times,
        'labor_requests': labor_requests,
    }
    return render(request, 'callManager/event_detail.html', context)

@login_required
def manager_dashboard(request):
    # Ensure the user is a manager
    if not hasattr(request.user, 'manager'):
        return redirect('login')  # Or a custom "access denied" page
    
    manager = request.user.manager
    company = manager.company

    # Fetch company events
    events = Event.objects.filter(company=company).order_by('-event_date')
    
    # Quick stats
    total_events = events.count()
    
    # Calculate total labor needed, default to 0 if no labor requirements exist
    labor_agg = LaborRequirement.objects.filter(call_time__event__company=company).aggregate(total=Sum('needed_labor'))
    total_labor_needed = labor_agg['total'] if labor_agg['total'] is not None else 0
    
    total_requests = LaborRequest.objects.filter(labor_requirement__call_time__event__company=company).count()
    confirmed_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event__company=company,
        response='yes',
    ).count()

    context = {
        'company': company,
        'events': events,
        'total_events': total_events,
        'total_labor_needed': total_labor_needed,
        'total_requests': total_requests,
        'confirmed_requests': confirmed_requests,
    }
    return render(request, 'callManager/manager_dashboard.html', context)


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
def add_labor_to_call(request, call_time_id):
    manager = request.user.manager
    call_time = get_object_or_404(CallTime, id=call_time_id, event__company=manager.company)
    
    if request.method == "POST":
        form = LaborRequirementForm(request.POST, company=manager.company)
        if form.is_valid():
            labor_requirement = form.save(commit=False)
            labor_requirement.call_time = call_time
            labor_requirement.save()
            return redirect('event_detail', event_id=call_time.event.id)
    else:
        form = LaborRequirementForm(company=manager.company)
    
    context = {
        'form': form,
        'call_time': call_time,
    }
    return render(request, 'callManager/add_labor_to_call.html', context)


@login_required
def create_event(request):
    manager = request.user.manager  # Assumes Manager is linked to User via OneToOneField
    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.company = manager.company  # Tie event to manager's company
            event.created_by = manager      # Record which manager created it
            event.save()
            return redirect('event_detail', event_id=event.id)  # ReGdirect to event detail page
    else:
        form = EventForm()
    return render(request, 'callManager/create_event.html', {'form': form})


@login_required
def labor_type_list(request):
    manager = request.user.manager
    company = manager.company
    labor_types = LaborType.objects.filter(company=company).order_by('name')
    
    context = {
        'company': company,
        'labor_types': labor_types,
    }
    return render(request, 'callManager/labor_type_list.html', context)


@login_required
def add_worker(request):
    manager = request.user.manager
    if request.method == "POST":
        form = WorkerForm(request.POST, company=manager.company)
        if form.is_valid():
            form.save()
            return redirect('worker_list')
    else:
        form = WorkerForm(company=manager.company)
    
    context = {
        'form': form,
    }
    return render(request, 'callManager/add_worker.html', context)


@login_required
def worker_list(request):
    manager = request.user.manager
    workers = Worker.objects.filter(labor_types__company=manager.company).distinct().order_by('name')
    
    # Handle search query
    search_query = request.GET.get('search', '').strip()
    if search_query:
        workers = workers.filter(
            Q(name__icontains=search_query) |
            Q(phone_number__icontains=search_query)
        )
    
    context = {
        'workers': workers,
        'search_query': search_query,
    }
    
    # Check if this is an HTMX request
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'callManager/worker_list_partial.html', context)
    return render(request, 'callManager/worker_list.html', context)


@login_required
def edit_worker(request, worker_id):
    manager = request.user.manager
    worker = get_object_or_404(Worker, id=worker_id, labor_types__company=manager.company)
    
    if request.method == "POST":
        form = WorkerForm(request.POST, instance=worker, company=manager.company)
        if form.is_valid():
            form.save()
            return redirect('worker_list')
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
    workers = Worker.objects.filter(
        labor_types=labor_requirement.labor_type,
        labor_types__company=manager.company
    ).distinct()

    current_call_time = labor_requirement.call_time
    event_date = current_call_time.event.event_date
    current_datetime = datetime.combine(event_date, current_call_time.time)

    window_start = current_datetime - timedelta(hours=5)
    window_end = current_datetime + timedelta(hours=5)

    conflicting_requests = LaborRequest.objects.filter(
        worker__in=workers,
        labor_requirement__call_time__event__event_date=event_date,
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
            'status': 'Confirmed' if labor_request.response == 'yes' else 'Pending'
        }
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.response == 'yes':
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True

    if request.method == "POST":
        worker_ids = request.POST.getlist('worker_ids')
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        for worker_id in worker_ids:
            worker = Worker.objects.get(id=worker_id)
            labor_request, created = LaborRequest.objects.get_or_create(
                worker=worker,
                labor_requirement=labor_requirement,
                defaults={'requested': True}
            )
            if created or not labor_request.sms_sent:
                if worker.phone_number:
                    message = client.messages.create(
                        body=f"Autorigger request for {labor_requirement.labor_type.name} on {event_date} at {current_call_time.time} ({current_call_time.name}). Reply YES to confirm, NO to decline: {request.build_absolute_uri(labor_request.confirmation_url)}",
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=str(worker.phone_number)
                    )
                    labor_request.sms_sent = True
                    labor_request.save()
                    logger.info(f"SMS sent to {worker.name} at {worker.phone_number}: {message.sid}")
                else:
                    logger.warning(f"No phone number for {worker.name}, SMS not sent")
            if not created:
                labor_request.requested = True
                labor_request.save()
        return render(request, 'callManager/fill_labor_call_partial.html', {
            'labor_requirement': labor_requirement,
            'workers': workers,
            'worker_conflicts': worker_conflicts,
            'message': f"Requests sent to {len(worker_ids)} workers."
        })

    context = {
        'labor_requirement': labor_requirement,
        'workers': workers,
        'worker_conflicts': worker_conflicts,
    }
    return render(request, 'callManager/fill_labor_call_partial.html', context)


@login_required
def add_call_time(request, event_id):
    manager = request.user.manager
    event = get_object_or_404(Event, id=event_id, company=manager.company)
    
    if request.method == "POST":
        form = CallTimeForm(request.POST)
        if form.is_valid():
            call_time = form.save(commit=False)
            call_time.event = event
            call_time.save()
            return redirect('event_detail', event_id=event.id)
    else:
        form = CallTimeForm()
    
    context = {
        'form': form,
        'event': event,
    }
    return render(request, 'callManager/add_call_time.html', context)

@csrf_exempt
def sms_reply_webhook(request):
    if request.method == "POST":
        from_number = request.POST.get('From')
        body = request.POST.get('Body', '').strip().upper()
        logger.info(f"Received SMS from {from_number}: {body}")

        # Find the LaborRequest by worker phone number and token
        labor_request = LaborRequest.objects.filter(
            worker__phone_number=from_number,
            sms_sent=True,
            response__isnull=True  # Only update if not already responded
        ).order_by('-requested_at').first()

        if labor_request:
            if body in ['YES', 'NO', 'OTHER']:
                labor_request.response = body.lower()
                labor_request.responded_at = timezone.now()
                labor_request.save()
                logger.info(f"Updated LaborRequest {labor_request.id} with response: {body}")
                return HttpResponse("Response recorded", content_type="text/plain")
            else:
                logger.warning(f"Invalid response from {from_number}: {body}")
                return HttpResponse("Invalid response. Reply YES, NO, or OTHER.", content_type="text/plain")
        else:
            logger.warning(f"No matching LaborRequest found for {from_number}")
            return HttpResponse("No active request found.", content_type="text/plain")

    return HttpResponse("Invalid request method", status=400, content_type="text/plain")
