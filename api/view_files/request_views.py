
from datetime import datetime, timedelta
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from api.serializers import CallTimeSerializer, EventSerializer, LaborRequestSerializer, LaborRequirementSerializer, LaborTypeSerializer, WorkerSerializer
from callManager.models import CallTime, LaborRequest, LaborRequirement, Worker
import json

from callManager.views import generate_short_token

@api_view(['GET']) 
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def pending_count(request):
    user = request.user
    if hasattr(user, 'manager') and not hasattr(user, 'administrator'):
        manager = user.manager
        company = manager.company
        pending_requests = LaborRequest.objects.filter(
            labor_requirement__call_time__event__company=company,
            availability_response__isnull=True,
            sms_sent=True,
            labor_requirement__call_time__date__gte=timezone.now().date()
            )
        return Response({'count': pending_requests})
    elif hasattr(user, 'administrator'):
        pending_requests = LaborRequest.objects.filter(
            availability_response__isnull=True,
            sms_sent=True,
            labor_requirement__call_time__date__gte=timezone.now().date()
            ).count()
        return Response({'count': pending_requests})
    else:
        return Response({'count': 0})


@api_view(['GET']) 
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def declined_count(request):
    user = request.user
    if hasattr(user, 'manager') and not hasattr(user, 'administrator'):
        manager = user.manager
        company = manager.company
        declined_requests = LaborRequest.objects.filter(
            labor_requirement__call_time__event__company=company,
            availability_response='no',
            labor_requirement__call_time__date__gte=timezone.now().date()
            ).count()
        return Response({'count': declined_requests})
    elif hasattr(user, 'administrator'):
        declined_requests = LaborRequest.objects.filter(
            availability_response='no',
            labor_requirement__call_time__date__gte=timezone.now().date()
            ).count()
        return Response({'count': declined_requests})
    else:
        return Response({'count': 0})


@api_view(['GET']) 
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def call_time_list(request, slug):
    user = request.user
    
    if hasattr(user, 'manager'):
        manager = user.manager
    else:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    call_time = get_object_or_404(CallTime, slug=slug)

    event = call_time.event
    company = event.company
    if not manager.company == company:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    labor_requests = LaborRequest.objects.filter(labor_requirement__call_time=call_time)
    
    labor_type_set = set()
    for labor_request in labor_requests:
        labor_type_set.add(labor_request.labor_requirement.labor_type)
    labor_types = list(labor_type_set)

    ## serialized data
    call_time_serializer = CallTimeSerializer(call_time)
    labor_request_serializer = LaborRequestSerializer(labor_requests, many=True)
    labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
    event_serializer = EventSerializer(event)

    context = {
            'call_time': call_time_serializer.data,
            'labor_requests': labor_request_serializer.data,
            'labor_types': labor_type_serializer.data,
            'event': event_serializer.data,
        }

    return Response(context)


@api_view(['POST']) 
def request_action(request, token):
    data = json.loads(request.body)
    action = data.get('action')
    labor_request = get_object_or_404(LaborRequest, token_short=token)
    worker = labor_request.worker
    labor_requirement = labor_request.labor_requirement
    fcfs = labor_requirement.fcfs_positions
    response = data.get('response')
    
    if action == "available":
        if response not in ['yes', 'no']:
            return Response({'status': 'error', 'message': 'Invalid response'}, status=400)
        if response == 'yes':
            labor_request.availability_response = 'yes'
            if labor_request.is_reserved:
                labor_request.confirmed = True
            if fcfs > 0:
                labor_request.confirmed = True
                labor_requirement.fcfs_positions -= 1
                labor_requirement.save()
                
            labor_request.save()
        else:
            labor_request.availability_response = 'no'
            labor_request.save()
    elif action == "confirm":
        labor_request.availability_response = 'yes'
        labor_request.canceled = False
        labor_request.confirmed = True
        labor_request.save()
    elif action == "decline":
        labor_request.availability_response = 'no'
        labor_request.confirmed = False
        labor_request.save()
    elif action == "delete":
        labor_request.delete()
    elif action == "cancel":
        labor_request.confirmed = False
        worker.canceled_requests += 1
        worker.save()
        labor_request.availability_response = 'no'
        labor_request.canceled = True
        labor_request.save()
    elif action == "ncns":
        labor_request.availability_response = 'no'
        labor_request.confirmed = False
        labor_request.ncns = True
        labor_request.save()
        worker.nocallnoshow += 1
        worker.save()
    elif action == "showed_up":
        labor_request.ncns = False
        labor_request.confirmed = True
        labor_request.save()
        worker.nocallnoshow -= 1
        worker.save()
    else:
        return Response({'status': 'error', 'message': 'Invalid action'}, status=400)
    return Response({'status': 'success'})



@api_view(['GET']) 
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def fill_labor_request_list(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    
    manager = user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
    call_time = labor_requirement.call_time
    call_datetime = datetime.combine(call_time.date, call_time.time)

    labor_type = [labor_requirement.labor_type]

    company = labor_requirement.call_time.event.company
    if not manager.company == company:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    workers = Worker.objects.filter(company=labor_requirement.call_time.event.company)
    workers = workers.order_by('name')
    for worker in workers:
        worker.conflicts = []
        for labor_request in worker.labor_requests.all():
            if labor_request.labor_requirement == labor_requirement:
                worker.requested = True
                continue
            request_datetime = datetime.combine(
                labor_request.labor_requirement.call_time.date,
                labor_request.labor_requirement.call_time.time
            )
            
            if call_datetime - timedelta(hours=5) <= request_datetime <= call_datetime + timedelta(hours=5):
                conflict_info = {
                    'event': labor_request.labor_requirement.call_time.event.event_name,
                    'call_time': f"{labor_request.labor_requirement.call_time.name} at {labor_request.labor_requirement.call_time.time}",
                    'labor_type': labor_request.labor_requirement.labor_type.name,
                    'location': labor_request.labor_requirement.call_time.event.location_profile.name,
                    'availability_response': labor_request.availability_response,
                    'confirmed': labor_request.confirmed,
                    'canceled': labor_request.canceled,
                }
                worker.conflicts.append(conflict_info)
    
    #serializers
    serialized_workers = WorkerSerializer(workers, many=True)
    serialized_labor_requests = LaborRequestSerializer(labor_requirement.labor_requests.all(), many=True)
    serialized_labor_requirement = LaborRequirementSerializer(labor_requirement)
    serialized_call_time = CallTimeSerializer(call_time)
    serialized_event = EventSerializer(call_time.event)
    serialized_labor_type = LaborTypeSerializer(labor_type, many=True)



    context = {
            'workers': serialized_workers.data,
            'call_time': serialized_call_time.data,
            'labor_requirement': serialized_labor_requirement.data,
            'labor_requests': serialized_labor_requests.data,
            'event': serialized_event.data,
            'labor_type': serialized_labor_type.data,
    }
    return Response(context)


@api_view(['POST']) 
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def request_worker(request, slug):
    data = json.loads(request.body)
    worker_id = data.get('worker_id')
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    labor_requirement = get_object_or_404(LaborRequirement, slug=slug)
    company = labor_requirement.call_time.event.company
    if not manager.company == company:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    worker = get_object_or_404(Worker, id=worker_id)
    _, created = LaborRequest.objects.get_or_create(
        worker=worker,
        labor_requirement=labor_requirement,
        defaults={
            'requested': True,
            'sms_sent': False,
            'is_reserved': False,
            'token_short': generate_short_token()
        }
    )
    if not created:
        return Response({'status': 'error', 'message': 'Worker already requested'}, status=400)
        
    return Response({'status': 'success'})

