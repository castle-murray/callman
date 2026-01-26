from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import TimeEntrySerializer, LaborRequestTrackingSerializer, CallTimeSerializer, LaborTypeSerializer, CompanySerializer
from callManager.models import CallTime, LaborRequest, TimeEntry, MealBreak, LaborType

@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
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

