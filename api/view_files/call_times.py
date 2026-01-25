from datetime import datetime, timedelta
from django.db.models import Q, Count
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from callManager.models import(
        CallTime,
        Event,
        LaborRequest,
        LaborRequirement,
        LaborType,
        TimeChangeConfirmation,
        TimeEntry,
        MealBreak
        )
from api.serializers import (
        CallTimeSerializer,
        EventSerializer,
        CompanySerializer,
        LaborRequestSerializer,
        LaborRequirementCreateSerializer,
        LaborRequirementSerializer,
        LaborTypeSerializer,
        WorkerSerializer,
        )
import json
from callManager.views import generate_short_token, send_message

@api_view(['GET','POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def add_call_time(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    event = get_object_or_404(Event, slug=slug)
    if request.method == "POST":
        request.data['event'] = event.id
        from datetime import datetime
        date_obj = datetime.strptime(request.data['date'], '%Y-%m-%d').date()
        time_obj = datetime.strptime(request.data['time'], '%H:%M').time()
        call_unixtime = timezone.datetime.combine(date_obj, time_obj)
        serializer = CallTimeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(event=event)
            return Response(serializer.data, status=201)
        else:
            print(serializer.errors)
        return Response(serializer.errors, status=400)
    elif request.method == "GET":
        labor_types = LaborType.objects.filter(company=company)
        labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
        company_serializer = CompanySerializer(company)
        event_serializer = EventSerializer(event)
        context = {
            'event': event_serializer,
            'company': company_serializer,
            'labor_types': labor_type_serializer.data,
        }
        return Response(context)
    else:
        return Response({'status': 'error', 'message': 'Invalid request method'}, status=400)

@api_view(['PATCH'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def edit_call_time(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    original_time = call_time.call_unixtime
    company = call_time.event.company
    serializer = CallTimeSerializer(call_time, data=request.data, partial=True)

    if serializer.is_valid():
        updated_call_time = serializer.save()
        updated_call_time.update_call_unixtime()
        new_time = updated_call_time.call_unixtime

        if original_time != new_time:
            call_time.time_has_changed = True
            call_time.save()
            confirmed_requests = LaborRequest.objects.filter(
                labor_requirement__call_time=call_time,
                confirmed=True,
            ).select_related('worker')
            sms_errors = []
            for req in confirmed_requests:
                worker = req.worker
                confirmation = TimeChangeConfirmation.objects.create(
                    labor_request=req,
                    expires_at=timezone.now() + timezone.timedelta(days=7),
                )
                confirm_url = request.build_absolute_uri(
                    f"/call/confirm-time-change/{confirmation.token}/"
                )
                message_body = (
                    f"{company.name_short or company.name}: {call_time.event.event_name} {call_time.name} time changed. "
                    f"Now: {updated_call_time.date.strftime('%B %d')} at {updated_call_time.time.strftime('%I:%M %p')}. "
                    f"Confirm: {confirm_url}"
                )
                sms_errors.extend(send_message(message_body, worker, manager, company))
            if sms_errors:
                return Response({'status': 'error', 'message': f"Errors: {len(sms_errors)}/{len(confirmed_requests)}"})

        return Response({'status': 'success', 'call_time': CallTimeSerializer(updated_call_time).data})
    return Response(serializer.errors, status=400)


@api_view(['DELETE'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_call_time(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    call_time.delete()
    return Response({'status': 'success', 'message': 'Call time deleted'})

@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def confirm_time_change_api(request, token):
    confirmation = get_object_or_404(
            TimeChangeConfirmation,
            token=token,
            expires_at__gt=timezone.now(),
            confirmed=False
            )
    labor_request = confirmation.labor_request
    call_time = labor_request.labor_requirement.call_time
    event = call_time.event
    if request.method == 'GET':
        # Return data for the form
        event_name = event.event_name
        call_time = labor_request.labor_requirement.call_time
        call_time_name = call_time.name
        original_time = f"{call_time.original_date} at {call_time.original_time.strftime('%I:%M %p')}" if call_time.original_time else "N/A"
        new_time = f"{call_time.date} at {call_time.time.strftime('%I:%M %p')}"
        context = {
            'event_name': event_name,
            'call_time_name': call_time_name,
            'original_time': original_time,
            'new_time': new_time,
            'messages': []  # No messages initially
        }
        return Response(context)
    elif request.method == 'POST':
        confirmation.confirmed = True
        confirmation.labor_request.save()
        confirmation.cant_do_it = request.data.get('cant_do_it') == 'true'
        confirmation.message = request.data.get('message')
        confirmation.save()
        return Response({'status': 'success', 'message': 'Confirmation processed'})

@api_view(['GET', 'POST'])
def call_time_tracking(request, slug):
    user = request.user
    if not hasattr(user, 'administrator') and not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    if hasattr(user, 'administrator'):
        call_time = get_object_or_404(CallTime, slug=slug)
        company = call_time.event.company
    else:
        manager = user.manager
        company = manager.company
        call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)

    if request.method == 'GET':
        labor_requests = LaborRequest.objects.filter(
            labor_requirement__call_time=call_time,
            confirmed=True).select_related('worker', 'labor_requirement__labor_type')
        labor_type_filter = request.GET.get('labor_type', 'All')
        if labor_type_filter != 'All':
            labor_requests = labor_requests.filter(labor_requirement__labor_type__id=labor_type_filter)

        confirmed_requests = []
        ncns_requests = []
        for lr in labor_requests:
            time_entry = lr.time_entries.first()
            if time_entry:
                meal_breaks = time_entry.meal_breaks.all()
                time_entry_data = {
                    'id': time_entry.id,
                    'start_time': time_entry.start_time.isoformat() if time_entry.start_time else None,
                    'end_time': time_entry.end_time.isoformat() if time_entry.end_time else None,
                    'meal_breaks': [{'id': mb.id, 'break_time': mb.break_time.isoformat(), 'duration': mb.duration.total_seconds() / 60 if mb.duration else 0, 'break_type': mb.break_type} for mb in meal_breaks]
                }
            else:
                time_entry_data = None
            lr_data = {
                'id': lr.id,
                'worker': {
                    'id': lr.worker.id,
                    'name': lr.worker.name,
                    'phone_number': lr.worker.phone_number,
                    'nocallnoshow': lr.worker.nocallnoshow
                },
                'labor_requirement': {
                    'id': lr.labor_requirement.id,
                    'labor_type': {
                        'id': lr.labor_requirement.labor_type.id,
                        'name': lr.labor_requirement.labor_type.name
                    },
                    'minimum_hours': lr.labor_requirement.minimum_hours
                },
                'time_entry': time_entry_data
            }
            if lr.availability_response == 'no' and lr.worker.nocallnoshow > 0:
                ncns_requests.append(lr_data)
            else:
                confirmed_requests.append(lr_data)

        labor_types = LaborType.objects.filter(company=company)
        meal_penalty_trigger_time = call_time.event.location_profile.meal_penalty_trigger_time or company.meal_penalty_trigger_time or datetime.time(18, 0)
        meal_penalty_diff = company.meal_penalty_diff or 1.5

        return Response({
            'call_time': CallTimeSerializer(call_time).data,
            'confirmed_requests': confirmed_requests,
            'ncns_requests': ncns_requests,
            'labor_types': LaborTypeSerializer(labor_types, many=True).data,
            'selected_labor_type': labor_type_filter,
            'meal_penalty_trigger_time': meal_penalty_trigger_time.strftime('%H:%M'),
            'meal_penalty_diff': meal_penalty_diff
        })
    elif request.method == 'POST':
        request_id = request.data.get('request_id')
        action = request.data.get('action')
        labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
        minimum_hours = labor_request.labor_requirement.minimum_hours or call_time.minimum_hours or call_time.event.location_profile.minimum_hours or company.minimum_hours
        worker = labor_request.worker
        if action in ['sign_in', 'sign_out', 'ncns', 'call_out', 'update_start_time', 'update_end_time', 'add_meal_break', 'update_meal_break', 'delete_meal_break']:
            time_entry, created = TimeEntry.objects.get_or_create(
                labor_request=labor_request,
                worker=worker,
                call_time=call_time,
                defaults={'start_time': datetime.combine(call_time.date, call_time.time)})
            was_ncns = worker.nocallnoshow > 0 and labor_request.availability_response == 'no'
            if action == 'sign_in' and not time_entry.start_time:
                time_entry.start_time = datetime.combine(call_time.date, call_time.time)
                time_entry.save()
            elif action == 'sign_out' and time_entry.start_time and not time_entry.end_time:
                end_time = datetime.now()
                if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
                    end_time = time_entry.start_time + timedelta(hours=minimum_hours)
                minutes = end_time.minute
                round_up = call_time.event.location_profile.hour_round_up or company.hour_round_up or 0
                if minutes > 30 + round_up:
                    end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                elif minutes > round_up:
                    end_time = end_time.replace(minute=30, second=0, microsecond=0)
                else:
                    end_time = end_time.replace(minute=0, second=0, microsecond=0)
                time_entry.end_time = end_time
                time_entry.save()
            elif action == 'ncns' and not was_ncns:
                labor_request.confirmed = False
                labor_request.availability_response = 'no'
                labor_request.save()
                worker.nocallnoshow += 1
                worker.save()
            elif action == 'update_start_time':
                new_time_str = request.data.get('new_time')
                time_entry.start_time = datetime.fromisoformat(new_time_str)
                time_entry.save()
            elif action == 'update_end_time':
                new_time_str = request.data.get('new_time')
                time_entry.end_time = datetime.fromisoformat(new_time_str)
                time_entry.save()
            elif action == 'add_meal_break':
                type_minutes = int(request.data.get('type', '30'))
                break_time = datetime.now()
                duration = timedelta(minutes=type_minutes)
                break_type = 'paid' if type_minutes == 30 else 'unpaid'
                MealBreak.objects.create(time_entry=time_entry, break_time=break_time, duration=duration, break_type=break_type)
                if type_minutes == 60:  # walk away
                    time_entry.end_time = break_time
                    time_entry.save()
            elif action == 'update_meal_break':
                meal_break_id = request.data.get('meal_break_id')
                meal_break = MealBreak.objects.get(id=meal_break_id, time_entry=time_entry)
                break_time_str = request.data.get('break_time')
                duration_min = int(request.data.get('duration'))
                meal_break.break_time = datetime.fromisoformat(break_time_str)
                meal_break.duration = timedelta(minutes=duration_min)
                meal_break.break_type = 'paid' if duration_min == 30 else 'unpaid'
                meal_break.save()
            elif action == 'delete_meal_break':
                meal_break_id = request.data.get('meal_break_id')
                MealBreak.objects.filter(id=meal_break_id).delete()
            # Other actions can be added similarly
        return Response({'status': 'success'})


@api_view(['GET'])
def call_time_confirmations(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    call_time = get_object_or_404(CallTime, slug=slug, event__company=user.manager.company)
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        confirmed=True
    ).select_related('worker', 'labor_requirement__labor_type')
    cant_do_it_requests = labor_requests.filter(time_change_confirmations__cant_do_it=True)
    confirmed_requests = labor_requests.filter(time_change_confirmations__confirmed=True).exclude(time_change_confirmations__cant_do_it=True)
    unconfirmed_requests = labor_requests.filter(time_change_confirmations__confirmed=False).exclude(time_change_confirmations__cant_do_it=True)
    from api.serializers import CallTimeSerializer, LaborRequestSerializer
    return Response({
        'call_time': CallTimeSerializer(call_time).data,
        'confirmed_requests': LaborRequestSerializer(confirmed_requests, many=True).data,
        'unconfirmed_requests': LaborRequestSerializer(unconfirmed_requests, many=True).data,
        'cant_do_it_requests': LaborRequestSerializer(cant_do_it_requests, many=True).data,
    })

@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def copy_call_time(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    original_call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    event = original_call_time.event
    formdata = request.data.copy()
    formdata['event'] = event.id
    from datetime import datetime
    date_obj = datetime.strptime(formdata['date'], '%Y-%m-%d').date()
    time_obj = datetime.strptime(formdata['time'], '%H:%M').time()
    call_unixtime = timezone.datetime.combine(date_obj, time_obj)
    formdata['call_unixtime'] = call_unixtime
    serializer = CallTimeSerializer(data=formdata)
    if serializer.is_valid():
        new_call_time = serializer.save(event=event)
        # Copy labor_requirements
        for lr in original_call_time.labor_requirements.all():
            new_lr = LaborRequirement.objects.create(
                call_time=new_call_time,
                labor_type=lr.labor_type,
                needed_labor=lr.needed_labor,
                fcfs_positions=lr.fcfs_positions,
                minimum_hours=lr.minimum_hours
            )
            # Copy all labor_requests as fresh
            for original_req in lr.labor_requests.all():
                LaborRequest.objects.create(
                    labor_requirement=new_lr,
                    worker=original_req.worker,
                    requested=True,
                    availability_response=None,
                    confirmed=False,
                    sms_sent=False,
                    event_token=None,
                    token_short=generate_short_token(),
                    responded_at=None,
                    canceled=False,
                    is_reserved=original_req.is_reserved
                )
        return Response(CallTimeSerializer(new_call_time).data, status=201)
    return Response(serializer.errors, status=400)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def send_call_time_messages(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    call_time = get_object_or_404(CallTime, slug=slug, event__company=manager.company)
    company = call_time.event.company
    queued_requests = LaborRequest.objects.filter(
        labor_requirement__call_time=call_time,
        requested=True,
        sms_sent=False
    ).select_related('worker')
    if not queued_requests.exists():
        return Response({'status': 'success', 'message': 'No queued requests to send.'})
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
        for labor_request in requests:
            if not labor_request.token_short:
                labor_request.token_short = generate_short_token()
            confirmation_url = request.build_absolute_uri(f"/event/{call_time.event.slug}/confirm/{labor_request.token_short}/")
            if call_time.event.is_single_day:
                message_body = f"This is {manager.user.first_name}/{company.name_short or company.name}: Confirm availability for {call_time.event.event_name} - {call_time.name} on {call_time.event.start_date} at {call_time.time.strftime('%I:%M %p')}: {confirmation_url}"
            else:
                message_body = f"This is {manager.user.first_name}/{company.name_short or company.name}: Confirm availability for {call_time.event.event_name} - {call_time.name} on {call_time.date} at {call_time.time.strftime('%I:%M %p')}: {confirmation_url}"
            sms_errors.extend(send_message(message_body, worker, manager, company))
            if worker.sms_consent == True:
                labor_request.sms_sent = True
            labor_request.save()
    message = f"Messages processed for {len(workers_to_notify)} workers."
    if sms_errors:
        message += f" Errors: {', '.join(sms_errors)}."
    return Response({'status': 'success', 'message': message})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def add_labor_to_call(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    call_time = get_object_or_404(CallTime, slug=slug, event__company=company)
    if request.method == "POST":
        serializer = LaborRequirementCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Remove the problematic line and just save with call_time
            serializer.save(call_time=call_time)
            return Response(serializer.data, status=201)
        else:
            return Response(serializer.errors, status=400)
    elif request.method == "GET":
        labor_types = LaborType.objects.filter(company=company)
        labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
        call_time_serializer = CallTimeSerializer(call_time)
        event_serializer = EventSerializer(call_time.event)
        context = {
            'call_time': call_time_serializer.data,
            'labor_types': labor_type_serializer.data,
            'event': event_serializer.data,
        }
        return Response(context)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def labor_requirement_status(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
    lr_serializer = LaborRequirementSerializer(labor_requirement)
    company = labor_requirement.call_time.event.company
    if not manager.company == company:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    if request.method == "GET":
        labor_requests = LaborRequest.objects.filter(labor_requirement=labor_requirement)
        pending = labor_requests.filter(availability_response__isnull=True).count()
        confirmed = labor_requests.filter(confirmed=True).count()
        available = labor_requests.filter(availability_response='yes', confirmed=False).count()
        declined = labor_requests.filter(availability_response='no').count()
        labor_type = labor_requirement.labor_type
        context = {
            'job': labor_type.name,
            'labor_requirement': lr_serializer.data,
            'pending': pending,
            'confirmed': confirmed,
            'available': available,
            'declined': declined,
        }
        return Response(context)
    else:
        return Response({'status': 'error', 'message': 'Invalid request method'}, status=400)


@api_view(['POST', 'GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def edit_labor_requirement(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
    call_time = labor_requirement.call_time
    event = call_time.event
    company = event.company
    if not manager.company == company:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    if request.method == "POST":
        serializer = LaborRequirementSerializer(labor_requirement, data=request.data)
        if serializer.is_valid():
            serializer.save(call_time=call_time)
            return Response({'status': 'success', 'message': 'Labor requirement updated', 'event_slug': event.slug})
        else:
            return Response(serializer.errors, status=400)
    elif request.method == "GET":
        labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
        labor_requirement_serializer = LaborRequirementSerializer(labor_requirement)
        context = {
            'labor_requirement': labor_requirement_serializer.data,
            'event_slug': event.slug
        }
        return Response(context, status=200)
    else:
        return Response({'status': 'error', 'message': 'Invalid request method'}, status=400)


@api_view(['DELETE'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_labor_requirement(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
    call_time = labor_requirement.call_time
    event = call_time.event
    company = event.company
    if not manager.company == company:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    if request.method == "DELETE":
        labor_requirement.delete()
        return Response({'status': 'success', 'message': 'Labor requirement deleted', 'event_slug': event.slug})
    else:
        return Response({'status': 'error', 'message': 'Invalid request method'}, status=400)
