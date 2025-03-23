from django.shortcuts import render, get_object_or_404, redirect
from .models import CallTime, LaborRequest, Event, LaborRequirement, LaborType, Worker
from django.contrib.auth.decorators import login_required
from .forms import CallTimeForm, LaborTypeForm, LaborRequirementForm, EventForm, WorkerForm, WorkerImportForm
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, timedelta
from twilio.rest import Client
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from io import TextIOWrapper
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


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
    
    # Get all labor requirements for the event
    labor_requirements = LaborRequirement.objects.filter(call_time__event=event)
    
    # Annotate labor requests with counts
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event
    ).values('labor_requirement_id').annotate(
        pending_count=Count('id', filter=Q(requested=True) & Q(response__isnull=True)),  # Only pending
        confirmed_count=Count('id', filter=Q(response='yes')),
        rejected_count=Count('id', filter=Q(response='no'))
    )
    
    # Build labor_counts with defaults and display text
    labor_counts = {lr.id: {'pending': 0, 'confirmed': 0, 'rejected': 0, 'display_text': f"{lr.needed_labor} needed (0 pending, 0 confirmed, 0 rejected)"} for lr in labor_requirements}
    for lr in labor_requests:
        labor_id = lr['labor_requirement_id']
        pending = lr['pending_count']
        confirmed = lr['confirmed_count']
        rejected = lr['rejected_count']
        needed = labor_requirements.get(id=labor_id).needed_labor
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
        
        labor_counts[labor_id] = {
            'pending': pending,
            'confirmed': confirmed,
            'rejected': rejected,
            'display_text': display_text
        }
    
    context = {
        'event': event,
        'call_times': call_times,
        'labor_counts': labor_counts,
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
    workers = Worker.objects.all().order_by('name')
    
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
    worker = get_object_or_404(Worker, id=worker_id)  # No company filter
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
    
    workers = Worker.objects.annotate(
        has_labor_type=Case(
            When(labor_types=labor_requirement.labor_type, then=0),
            default=1,
            output_field=IntegerField()
        )
    ).order_by('has_labor_type', 'name')

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

    # In both fill_labor_call and fill_labor_call_list
    worker_conflicts = {}
    for labor_request in conflicting_requests:
        if labor_request.worker_id not in worker_conflicts:
            worker_conflicts[labor_request.worker_id] = {'conflicts': [], 'is_confirmed': False}
        conflict_info = {
            'event': labor_request.labor_requirement.call_time.event.event_name,
            'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
            'labor_type': labor_request.labor_requirement.labor_type.name,
            'status': 'Confirmed' if labor_request.response == 'yes' else 'Rejected' if labor_request.response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,  # Add call time ID
            'labor_type_id': labor_request.labor_requirement.labor_type.id  # Add labor type ID
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
                defaults={'requested': True}
            )
            if labor_requirement.labor_type not in worker.labor_types.all():
                worker.labor_types.add(labor_requirement.labor_type)
            if created or not labor_request.sms_sent:
                short_id = str(labor_request.token)[:3]  # First 3 chars of UUID
                if worker.phone_number and settings.TWILIO_ENABLED:
                    try:
                        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                        message = client.messages.create(
                            body=f"Autorigger call {current_call_time.name} at {current_call_time.time}. Reply Y{short_id} or N{short_id}.",
                            from_=settings.TWILIO_PHONE_NUMBER,
                            to=str(worker.phone_number)
                        )
                        labor_request.sms_sent = True
                        labor_request.save()
                    except TwilioRestException as e:
                        sms_errors.append(worker.name)
                elif worker.phone_number:
                    labor_request.sms_sent = True
                    labor_request.save()
                else:
                    sms_errors.append(f"{worker.name} (no phone)")
            if not created:
                labor_request.requested = True
                labor_request.save()
        message = f"Requests sent to {len(worker_ids)} workers."
        if sms_errors:
            message += f" SMS failed for: {', '.join(sms_errors)}."
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
    
    workers = Worker.objects.annotate(
        has_labor_type=Case(
            When(labor_types=labor_requirement.labor_type, then=0),
            default=1,
            output_field=IntegerField()
        )
    ).order_by('has_labor_type', 'name')

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
            'status': 'Confirmed' if labor_request.response == 'yes' else 'Rejected' if labor_request.response == 'no' else 'Pending',
            'call_time_id': labor_request.labor_requirement.call_time.id,  # Add call time ID
            'labor_type_id': labor_request.labor_requirement.labor_type.id  # Add labor type ID
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
