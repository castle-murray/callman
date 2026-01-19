from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import(
        CallTime,
        Event,
        LaborRequest,
        LaborRequirement,
        LaborType,
        )
from api.serializers import (
        CallTimeSerializer,
        EventSerializer,
        CompanySerializer,
        LaborRequirementCreateSerializer,
        LaborRequirementSerializer,
        LaborTypeSerializer,
        )
import json

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
