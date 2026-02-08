from django.utils import timezone
from datetime import datetime, timedelta
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from api.serializers import TimeEntrySerializer, LaborRequestTrackingSerializer, CallTimeSerializer, LaborTypeSerializer, CompanySerializer
from callManager.models import CallTime, LaborRequest, TimeEntry, MealBreak, LaborType, ClockInToken, TemporaryScanner

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def call_time_tracking(request, slug):
    user = request.user
    if hasattr(user, 'administrator'):
        call_time = get_object_or_404(CallTime, slug=slug)
        company = call_time.event.company
    elif hasattr(user, 'manager'):
        company = user.manager.company
        call_time = get_object_or_404(CallTime, slug=slug, event__company=company)
    elif hasattr(user, 'steward'):
        company = user.steward.company
        call_time = get_object_or_404(CallTime, slug=slug, event__company=company)
        if call_time.event.steward != user.steward:
            return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    else:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    if request.method == 'GET':
        labor_requests = LaborRequest.objects.filter(
            labor_requirement__call_time=call_time,
            confirmed=True).select_related('worker', 'labor_requirement__labor_type')
        lr_data_list = LaborRequestTrackingSerializer(labor_requests, many=True).data
        labor_types = LaborType.objects.filter(id__in=labor_requests.values_list('labor_requirement__labor_type', flat=True).distinct())
        return Response({
            'call_time': CallTimeSerializer(call_time).data,
            'labor_requests': lr_data_list,
            'labor_types': LaborTypeSerializer(labor_types, many=True).data,
            'company_name': company.name
        })
    elif request.method == 'POST':
        request_id = request.data.get('request_id')
        action = request.data.get('action')
        labor_request = get_object_or_404(LaborRequest, id=request_id, labor_requirement__call_time=call_time)
        minimum_hours = labor_request.labor_requirement.minimum_hours or call_time.minimum_hours or call_time.event.location_profile.minimum_hours or company.minimum_hours
        worker = labor_request.worker
        def round_time(dt, target):
            if target == 0:
                # round to nearest hour
                if dt.minute >= 30:
                    dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                else:
                    dt = dt.replace(minute=0, second=0, microsecond=0)
            else:
                # round to nearest target
                rounded_min = round(dt.minute / target) * target
                if rounded_min == 60:
                    dt = dt.replace(hour=dt.hour + 1, minute=0, second=0, microsecond=0)
                else:
                    dt = dt.replace(minute=rounded_min, second=0, microsecond=0)
            return dt

        if action in ['sign_in', 'sign_out', 'ncns', 'call_out', 'update_start_time', 'update_end_time', 'add_meal_break', 'update_meal_break', 'delete_meal_break']:
            time_entry, created = TimeEntry.objects.get_or_create(
                labor_request=labor_request,
                worker=worker,
                call_time=call_time,
                defaults={'start_time': datetime.combine(call_time.date, call_time.time)})
            was_ncns = worker.nocallnoshow > 0 and labor_request.availability_response == 'no'
            if action == 'sign_in' and not time_entry.start_time:
                start_time = datetime.combine(call_time.date, call_time.time)
                time_entry.start_time = round_time(start_time, company.round_up_target or 30)
                time_entry.save()
            elif action == 'sign_out' and time_entry.start_time and not time_entry.end_time:
                end_time = datetime.now()
                if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
                    end_time = time_entry.start_time + timedelta(hours=minimum_hours)
                minutes = end_time.minute
                location_profile = call_time.event.location_profile
                round_up = (location_profile.hour_round_up if location_profile else None) or company.hour_round_up or 4
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
                labor_request.ncns = True
                labor_request.save()
                worker.nocallnoshow += 1
                worker.save()
            elif action == 'update_start_time':
                new_time_str = request.data.get('new_time')
                dt = datetime.fromisoformat(new_time_str)
                rounded_dt = round_time(dt, company.round_up_target or 30)
                time_entry.start_time = rounded_dt
                time_entry.save()
            elif action == 'update_end_time':
                new_time_str = request.data.get('new_time')
                dt = datetime.fromisoformat(new_time_str)
                rounded_dt = round_time(dt, company.round_up_target or 30)
                time_entry.end_time = rounded_dt
                time_entry.save()
            elif action == 'add_meal_break':
                type_minutes = int(request.data.get('type', '30'))
                break_time_str = request.data.get('break_time')
                if break_time_str:
                    break_time = datetime.fromisoformat(break_time_str)
                    break_time = round_time(break_time, company.round_up_target or 30)
                else:
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
                break_time = datetime.fromisoformat(break_time_str)
                break_time = round_time(break_time, company.round_up_target or 30)
                meal_break.break_time = break_time
                meal_break.duration = timedelta(minutes=duration_min)
                meal_break.break_type = 'paid' if duration_min == 30 else 'unpaid'
                meal_break.save()
            elif action == 'delete_meal_break':
                meal_break_id = request.data.get('meal_break_id')
                MealBreak.objects.filter(id=meal_break_id).delete()
            # Other actions can be added similarly
        return Response({'status': 'success'})


@api_view(['GET', 'POST'])
def worker_clock_in_out_api(request, token):
    token_obj = get_object_or_404(ClockInToken, token=token)
    if token_obj.expires_at < timezone.now():
        return Response({'status': 'error', 'message': 'This clock-in link has expired.'}, status=400)
    event = token_obj.event
    worker = token_obj.worker
    company = event.company
    if request.method == 'GET':
        call_times = CallTime.objects.filter(
            event=event,
            labor_requirements__labor_requests__worker=worker,
            labor_requirements__labor_requests__confirmed=True
        ).distinct().order_by('date', 'time')
        call_times_data = []
        for ct in call_times:
            is_signed_in = TimeEntry.objects.filter(
                worker=worker,
                call_time=ct,
                start_time__isnull=False,
                end_time__isnull=True
            ).exists()
            labor_request = LaborRequest.objects.get(worker=worker, labor_requirement__call_time=ct, confirmed=True)
            role = labor_request.labor_requirement.labor_type.name
            call_times_data.append({
                'id': ct.id,
                'date': str(ct.date),
                'time': ct.time.strftime('%I:%M %p'),
                'title': ct.title,
                'role': role,
                'is_signed_in': is_signed_in
            })
        return Response({
            'event': {'name': event.event_name, 'slug': event.slug},
            'worker': {'name': worker.name, 'slug': worker.slug},
            'call_times': call_times_data
        })
    elif request.method == 'POST':
        call_time_id = request.data.get('call_time_id')
        action = request.data.get('action')
        call_time = get_object_or_404(CallTime, id=call_time_id, event=event)
        labor_request = get_object_or_404(LaborRequest, worker=worker, labor_requirement__call_time=call_time, confirmed=True)
        minimum_hours = labor_request.labor_requirement.minimum_hours or call_time.minimum_hours or event.location_profile.minimum_hours or company.minimum_hours
        time_entry, created = TimeEntry.objects.get_or_create(
            labor_request=labor_request,
            worker=worker,
            call_time=call_time,
            defaults={'start_time': None, 'end_time': None}
        )
        if action == 'clock_in':
            now = timezone.now()
            call_datetime = datetime.combine(call_time.date, call_time.time)
            if abs((now - call_datetime).total_seconds()) > 3600:
                return Response({'status': 'error', 'message': 'Please contact your steward for clocking in outside the allowed time.'}, status=400)
            if not time_entry.start_time:
                time_entry.start_time = call_datetime
                time_entry.save()
                message = f"Signed in at {time_entry.start_time.strftime('%I:%M %p')}."
            else:
                return Response({'status': 'error', 'message': 'Already clocked in.'}, status=400)
        elif action == 'clock_out' and time_entry.start_time and not time_entry.end_time:
            end_time = timezone.now()
            minutes = end_time.minute
            round_up = event.location_profile.hour_round_up or company.hour_round_up
            if minutes > 30 + round_up:
                end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            elif minutes > round_up:
                end_time = end_time.replace(minute=30, second=0, microsecond=0)
            else:
                end_time = end_time.replace(minute=0, second=0, microsecond=0)
            if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
                end_time = time_entry.start_time + timedelta(hours=minimum_hours)
            time_entry.end_time = end_time
            time_entry.save()
            message = f"Signed out at {time_entry.end_time.strftime('%I:%M %p')}."
        else:
            return Response({'status': 'error', 'message': 'Invalid action or time entry state.'}, status=400)
        return Response({'status': 'success', 'message': message})


def _perform_qr_clock(event, worker, company):
    """Shared clock in/out logic for QR-based scanning.
    Returns (success: bool, message: str).
    """
    now = timezone.now()
    one_hour_before = now - timedelta(hours=1)
    one_hour_after = now + timedelta(hours=1)
    call_times = CallTime.objects.filter(
        event=event,
        labor_requirements__labor_requests__worker=worker,
        labor_requirements__labor_requests__confirmed=True
    ).exclude(
        timeentry__worker=worker,
        timeentry__start_time__isnull=False,
        timeentry__end_time__isnull=False
    ).distinct()
    valid_call_times = []
    for ct in call_times:
        call_datetime = datetime.combine(ct.date, ct.time)
        if one_hour_before <= call_datetime <= one_hour_after or TimeEntry.objects.filter(worker=worker, call_time=ct, start_time__isnull=False, end_time__isnull=True).exists():
            valid_call_times.append(ct)
    if len(valid_call_times) != 1:
        return (False, 'No single relevant call time found.')
    call_time = valid_call_times[0]
    labor_request = LaborRequest.objects.get(worker=worker, labor_requirement__call_time=call_time, confirmed=True)
    location_profile = event.location_profile
    minimum_hours = labor_request.labor_requirement.minimum_hours or call_time.minimum_hours or (location_profile.minimum_hours if location_profile else None) or company.minimum_hours
    time_entry, created = TimeEntry.objects.get_or_create(
        labor_request=labor_request,
        worker=worker,
        call_time=call_time,
        defaults={'start_time': None, 'end_time': None}
    )
    if time_entry.start_time and not time_entry.end_time:
        # Clock out
        end_time = timezone.now()
        minutes = end_time.minute
        round_up = (location_profile.hour_round_up if location_profile else None) or company.hour_round_up or 4
        if minutes > 30 + round_up:
            end_time = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif minutes > round_up:
            end_time = end_time.replace(minute=30, second=0, microsecond=0)
        else:
            end_time = end_time.replace(minute=0, second=0, microsecond=0)
        if time_entry.start_time + timedelta(hours=minimum_hours) > end_time:
            end_time = time_entry.start_time + timedelta(hours=minimum_hours)
        time_entry.end_time = end_time
        time_entry.save()
        return (True, f"Signed out at {time_entry.end_time.strftime('%I:%M %p')}.")
    elif not time_entry.start_time:
        # Clock in
        time_entry.start_time = datetime.combine(call_time.date, call_time.time)
        time_entry.save()
        return (True, f"Signed in at {time_entry.start_time.strftime('%I:%M %p')}.")
    else:
        return (False, 'Invalid time entry state.')


@api_view(['POST'])
def worker_qr_clock(request, token):
    token_obj = get_object_or_404(ClockInToken, token=token)
    if token_obj.expires_at < timezone.now():
        return Response({'status': 'error', 'message': 'This clock-in link has expired.'}, status=400)
    event = token_obj.event
    worker = token_obj.worker
    company = event.company
    success, message = _perform_qr_clock(event, worker, company)
    if success:
        return Response({'status': 'success', 'message': message})
    else:
        return Response({'status': 'error', 'message': message}, status=400)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def validate_station(request, token):
    scanner = TemporaryScanner.objects.filter(token=token).first()
    if not scanner:
        return Response({'status': 'error', 'message': 'Invalid station token.'}, status=404)
    if scanner.expires_at < timezone.now():
        return Response({'status': 'error', 'message': 'This station has expired.'}, status=400)
    return Response({
        'event_name': scanner.event.event_name,
        'expires_at': scanner.expires_at.isoformat(),
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def station_clock(request, token):
    scanner = TemporaryScanner.objects.filter(token=token).first()
    if not scanner:
        return Response({'status': 'error', 'message': 'Invalid station token.'}, status=404)
    if scanner.expires_at < timezone.now():
        return Response({'status': 'error', 'message': 'This station has expired.'}, status=400)

    worker_token = request.data.get('worker_token')
    if not worker_token:
        return Response({'status': 'error', 'message': 'No worker token provided.'}, status=400)

    clock_token = ClockInToken.objects.filter(token=worker_token).first()
    if not clock_token:
        return Response({'status': 'error', 'message': 'Invalid worker QR code.'}, status=404)
    if clock_token.expires_at < timezone.now():
        return Response({'status': 'error', 'message': 'Worker clock-in token has expired.'}, status=400)
    if clock_token.event != scanner.event:
        return Response({'status': 'error', 'message': 'This QR code is for a different event.'}, status=400)

    event = scanner.event
    worker = clock_token.worker
    company = event.company

    success, message = _perform_qr_clock(event, worker, company)
    if success:
        return Response({'status': 'success', 'message': message, 'worker_name': worker.name})
    else:
        return Response({'status': 'error', 'message': message}, status=400)

