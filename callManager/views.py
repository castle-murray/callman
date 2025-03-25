from django.shortcuts import render, get_object_or_404, redirect
from .models import CallTime, LaborRequest, Event, LaborRequirement, LaborType, Worker
from django.contrib.auth.decorators import login_required
from .forms import CallTimeForm, LaborTypeForm, LaborRequirementForm, EventForm, WorkerForm, WorkerImportForm, WorkerRegistrationForm
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
    
    labor_requirements = LaborRequirement.objects.filter(call_time__event=event)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event
    ).values('labor_requirement_id').annotate(
        pending_count=Count('id', filter=Q(requested=True) & Q(response__isnull=True)),
        confirmed_count=Count('id', filter=Q(response='yes')),
        rejected_count=Count('id', filter=Q(response='no'))
    )
    
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
    
    if request.method == "POST" and 'send_messages' in request.POST:
        queued_requests = LaborRequest.objects.filter(
            labor_requirement__call_time__event=event,
            requested=True,
            sms_sent=False
        )
        if queued_requests.exists():
            event_token = str(uuid.uuid4())
            sms_errors = []
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED else None
            confirmation_url = request.build_absolute_uri(f"/event/{event.id}/confirm/{event_token}/")
            for labor_request in queued_requests:
                message_body = f"CallMan: Confirm your calls for {event.event_name}: {confirmation_url}"
                if labor_request.worker.phone_number:
                    if settings.TWILIO_ENABLED:
                        try:
                            message = client.messages.create(
                                body=message_body,
                                from_=settings.TWILIO_PHONE_NUMBER,
                                to=str(labor_request.worker.phone_number)
                            )
                            labor_request.sms_sent = True
                            labor_request.event_token = event_token
                            labor_request.save()
                        except TwilioRestException as e:
                            sms_errors.append(labor_request.worker.name)
                    else:
                        # Print to terminal instead of sending SMS
                        print(f"SMS to {labor_request.worker.phone_number}: {message_body}")
                        labor_request.sms_sent = True
                        labor_request.event_token = event_token
                        labor_request.save()
                else:
                    sms_errors.append(f"{labor_request.worker.name} (no phone)")
            message = f"Messages sent to {queued_requests.count()} workers."
            if sms_errors:
                message += f" SMS failed for: {', '.join(sms_errors)}."
        else:
            message = "No queued requests to send."
        context = {
            'event': event,
            'call_times': call_times,
            'labor_counts': labor_counts,
            'message': message,
        }
        return render(request, 'callManager/event_detail.html', context)

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
    events = Event.objects.filter(company=company).order_by('-start_date')
    
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
    manager = request.user.manager
    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.company = manager.company
            event.created_by = manager
            event.save()
            return redirect('event_detail', event_id=event.id)
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

    paginator = Paginator(workers, 20)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    current_call_time = labor_requirement.call_time
    event_date = current_call_time.event.start_date  # Updated from event_date
    current_datetime = datetime.combine(event_date, current_call_time.time)

    window_start = current_datetime - timedelta(hours=5)
    window_end = current_datetime + timedelta(hours=5)

    conflicting_requests = LaborRequest.objects.filter(
        worker__in=workers,
        labor_requirement__call_time__event__start_date=event_date,  # Updated from event_date
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
            'call_time_id': labor_request.labor_requirement.call_time.id,
            'labor_type_id': labor_request.labor_requirement.labor_type.id
        }
        worker_conflicts[labor_request.worker_id]['conflicts'].append(conflict_info)
        if labor_request.response == 'yes':
            worker_conflicts[labor_request.worker_id]['is_confirmed'] = True

    if request.method == "POST":
        if 'send_messages' in request.POST:
            # Send SMS to all queued requests for this labor_requirement
            queued_requests = LaborRequest.objects.filter(
                labor_requirement=labor_requirement,
                requested=True,
                sms_sent=False
            )
            sms_errors = []
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED else None
            for labor_request in queued_requests:
                short_id = str(labor_request.token)[:3]
                if labor_request.worker.phone_number and settings.TWILIO_ENABLED:
                    try:
                        message = client.messages.create(
                            body=f"CallMan call {current_call_time.name} at {current_call_time.time}. Reply Y{short_id} or N{short_id}.",
                            from_=settings.TWILIO_PHONE_NUMBER,
                            to=str(labor_request.worker.phone_number)
                        )
                        labor_request.sms_sent = True
                        labor_request.save()
                    except TwilioRestException as e:
                        sms_errors.append(labor_request.worker.name)
                elif labor_request.worker.phone_number:
                    labor_request.sms_sent = True  # Simulate in test mode
                    labor_request.save()
                else:
                    sms_errors.append(f"{labor_request.worker.name} (no phone)")
            message = f"Messages sent to {queued_requests.count()} workers."
            if sms_errors:
                message += f" SMS failed for: {', '.join(sms_errors)}."
        else:
            # Queue requests without sending SMS
            worker_ids = request.POST.getlist('worker_ids')
            sms_errors = []
            for worker_id in worker_ids:
                worker = Worker.objects.get(id=worker_id)
                labor_request, created = LaborRequest.objects.get_or_create(
                    worker=worker,
                    labor_requirement=labor_requirement,
                    defaults={'requested': True, 'sms_sent': False}  # Ensure sms_sent=False initially
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

    paginator = Paginator(workers, 20)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    current_call_time = labor_requirement.call_time
    event_date = current_call_time.event.start_date  # Updated from event_date
    current_datetime = datetime.combine(event_date, current_call_time.time)

    window_start = current_datetime - timedelta(hours=5)
    window_end = current_datetime + timedelta(hours=5)

    conflicting_requests = LaborRequest.objects.filter(
        worker__in=workers,
        labor_requirement__call_time__event__start_date=event_date,  # Updated from event_date
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
def add_call_time(request, event_id):
    manager = request.user.manager
    event = get_object_or_404(Event, id=event_id, company=manager.company)
    if request.method == "POST":
        form = CallTimeForm(request.POST, event=event)
        if form.is_valid():
            call_time = form.save(commit=False)
            call_time.event = event
            call_time.save()
            return redirect('event_detail', event_id=event.id)
    else:
        form = CallTimeForm(event=event)
    return render(request, 'callManager/add_call_time.html', {'form': form, 'event': event})


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


def confirm_event_requests(request, event_id, event_token):
    event = get_object_or_404(Event, id=event_id)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        event_token=event_token,
        requested=True,
        response__isnull=True
    ).select_related('labor_requirement__call_time', 'labor_requirement__labor_type')

    if not labor_requests.exists():
        return render(request, 'callManager/confirm_error.html', {'message': "No pending requests found for this link."})

    if request.method == "POST":
        for labor_request in labor_requests:
            response_key = f"response_{labor_request.id}"
            response = request.POST.get(response_key)
            if response in ['yes', 'no']:
                labor_request.response = response
                labor_request.responded_at = timezone.now()
                labor_request.save()
        return render(request, 'callManager/confirm_success.html', {'event': event})

    # Use the first labor request's phone number for registration link
    phone_number = labor_requests.first().worker.phone_number if labor_requests.exists() else ''
    registration_url = request.build_absolute_uri(f"/worker/register/?phone={phone_number}")

    context = {
        'event': event,
        'labor_requests': labor_requests,
        'registration_url': registration_url,
    }
    return render(request, 'callManager/confirm_event_requests.html', context)

def worker_registration(request):
    phone_number = request.GET.get('phone', '')
    if request.method == "POST":
        form = WorkerRegistrationForm(request.POST)
        if form.is_valid():
            worker = form.save(commit=False)
            # Check if phone number matches an existing worker
            existing_worker = Worker.objects.filter(phone_number=worker.phone_number).first()
            if existing_worker:
                # Update existing worker if phone matches, regardless of name
                existing_worker.name = worker.name
                existing_worker.labor_types.set(worker.labor_types.all())
                existing_worker.save()
            else:
                # Create new worker
                worker.save()
            return redirect('registration_success')
    else:
        form = WorkerRegistrationForm(initial={'phone_number': phone_number})
        form.fields['phone_number'].disabled = True  # Lock phone number

    context = {
        'form': form,
        'phone_number': phone_number,
    }
    return render(request, 'callManager/worker_registration.html', context)

def registration_success(request):
    return render(request, 'callManager/registration_success.html')
