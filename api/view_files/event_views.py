from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from callManager.models import Event, LaborRequirement, LaborType, LocationProfile
from api.serializers import (
        CallTimeSerializer,
        CompanySerializer,
        EventSerializer,
        LaborRequirementSerializer,
        LaborTypeSerializer,
        LocationProfileSerializer,
        )
from callManager.models import generate_unique_slug


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def list_events(request):
    user = request.user
    print(f"Authenticated user: {user}")  # Debug line
    
    if hasattr(user, 'manager') and not hasattr(user, 'administrator'):
        manager = user.manager
        company = manager.company
        events = Event.objects.filter(company=company)
        new_events = []
        for event in events:
            event.unfilled_count = 0
            event.filled = False
            for call_time in event.call_times.all():
                for labor_requirement in call_time.labor_requirements.all():
                    event.unfilled_count += max(0, labor_requirement.needed_labor - labor_requirement.labor_requests.filter(confirmed=True).count())
            if event.unfilled_count == 0:
                event.filled = True
            new_events.append(event)


        serializer = EventSerializer(new_events, many=True)
        return Response(serializer.data)

    elif hasattr(user, 'administrator'):
        events = Event.objects.all()
        new_events = []
        for event in events:
            event.unfilled_count = 0
            event.filled = False
            for call_time in event.call_times.all():
                for labor_requirement in call_time.labor_requirements.all():
                    event.unfilled_count += max(0, labor_requirement.needed_labor - labor_requirement.labor_requests.filter(confirmed=True).count())
            if event.unfilled_count == 0:
                event.filled = True
            new_events.append(event)
        serializer = EventSerializer(new_events, many=True)
        return Response(serializer.data)

    else:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)

@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def upcoming_event_count(request):
    user = request.user
    if hasattr(user, 'manager') and not hasattr(user, 'administrator'):
        manager = user.manager
        company = manager.company
        events = Event.objects.filter(company=company, end_date__gte=timezone.now().date())
        return Response({'count': events.count()})
    elif hasattr(user, 'administrator'):
        events = Event.objects.filter(end_date__gte=timezone.now().date())
        return Response({'count': events.count()})
    else:
        return 0


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def create_event(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    if request.method == "POST":
        serializer = EventSerializer(data=request.data)
        if serializer.is_valid():
            serializer.validated_data['company'] = company
            serializer.validated_data['created_by'] = manager
            serializer.validated_data['slug'] = generate_unique_slug(Event)
            serializer.validated_data['location_profile'] = get_object_or_404(LocationProfile, id=request.data['location_profile'])

            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == "GET":
        location_profiles = company.location_profiles.all()
        location_serializer = LocationProfileSerializer(location_profiles, many=True)
        company_serializer = CompanySerializer(company)
        
        context = {
            'location_profiles': location_serializer.data,
            'company': company_serializer.data
        }

        return Response(context)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def event_details(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, slug=slug)
    call_times = event.call_times.all()
    labor_types = LaborType.objects.filter(company=event.company)
    labor_requirements = LaborRequirement.objects.filter(call_time__event=event)
    calltime_serializer = CallTimeSerializer(call_times, many=True)
    event_serializer = EventSerializer(event)
    labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
    labor_requirement_serializer = LaborRequirementSerializer(labor_requirements, many=True)
    context = {
        'event': event_serializer.data,
        'call_times': calltime_serializer.data,
        'labor_types': labor_type_serializer.data,
        'labor_requirements': labor_requirement_serializer.data,
    }
    return Response(context)


