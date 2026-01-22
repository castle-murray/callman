<<<<<<< Updated upstream
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from callManager.models import Event, LaborRequirement, LaborType, LocationProfile
=======
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from callManager.models import (
        Event,
        LaborRequest,
        LaborRequirement,
        LaborType,
        LocationProfile,
        ClockInToken,
        Notifications
        )
import qrcode
from io import BytesIO
import base64
>>>>>>> Stashed changes
from api.serializers import (
        CallTimeSerializer,
        CompanySerializer,
        EventSerializer,
        LaborRequirementSerializer,
        LaborTypeSerializer,
        LocationProfileSerializer,
<<<<<<< Updated upstream
        )
from callManager.models import generate_unique_slug
=======
        WorkerSerializer,
        CallTimeSerializer,
        LaborRequestSerializer,
        )
from callManager.models import generate_unique_slug
from callManager.views import send_message, generate_short_token
from callManager.view_files.notify import notify
from django.db.models import Q, Count
from callManager.views import log_sms

>>>>>>> Stashed changes


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

<<<<<<< Updated upstream

=======
@permission_classes([AllowAny])
>>>>>>> Stashed changes
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


<<<<<<< Updated upstream
=======
@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def send_event_messages(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    event = get_object_or_404(Event, slug=slug, company=manager.company)
    company = event.company

    queued_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
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
        # Use existing token_short if available, otherwise generate new
        token = next((req.token_short for req in requests if req.token_short), generate_short_token())
        # For API, build URL assuming frontend handles it, but for now, use a placeholder
        confirmation_url = request.build_absolute_uri(f"/event/{event.slug}/confirm/{token}/")
        if event.is_single_day:
            message_body = f"This is {manager.user.first_name}/{company.name_short or company.name}: Confirm availability for {event.event_name} on {event.start_date}: {confirmation_url}"
        else:
            message_body = f"This is {manager.user.first_name}/{company.name_short or company.name}: Confirm availability for {event.event_name}: {confirmation_url}"
        if len(message_body) > 144:
            message_body = message_body[:141] + "..."
        sms_errors.extend(send_message(message_body, worker, manager, company))
        for labor_request in requests:
            if worker.sms_consent == True:
                labor_request.sms_sent = True
            labor_request.token_short = token
            labor_request.save()

    message = f"Messages processed for {len(workers_to_notify)} workers."
    if sms_errors:
        message += f" Errors: {', '.join(sms_errors)}."
    return Response({'status': 'success', 'message': message})

@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def confirm_requests(request, slug, event_token):
    print("Baocn")
    print(f"Request reached confirm_requests view: {request.method}")
    event = get_object_or_404(Event, slug=slug)
    company = event.company
    if len(event_token) > 6:
        first_request = LaborRequest.objects.filter(
            labor_requirement__call_time__event=event,
            event_token=event_token,
            worker__phone_number__isnull=False).select_related('worker').first()
    else:
        first_request = LaborRequest.objects.filter(
            labor_requirement__call_time__event=event,
            token_short=event_token,
            worker__phone_number__isnull=False).select_related('worker').first()
    if not first_request:
        return Response({'status': 'error', 'message': 'No requests found for this link.'}, status=404)
    worker = first_request.worker
    worker_phone = worker.phone_number
    labor_requests = LaborRequest.objects.filter(
        labor_requirement__call_time__event=event,
        requested=True,
        worker__phone_number=worker_phone).select_related(
        'labor_requirement__call_time',
        'labor_requirement__labor_type').annotate(
        confirmed_count=Count('labor_requirement__labor_requests', filter=Q(labor_requirement__labor_requests__confirmed=True))).order_by(
        'labor_requirement__call_time__date',
        'labor_requirement__call_time__time')
    labor_requests = labor_requests.filter(sms_sent=True)
    confirmed_call_times = labor_requests.filter(confirmed=True)
    pending_call_times = labor_requests.filter(availability_response__isnull=True)
    available_call_times = labor_requests.filter(availability_response='yes', confirmed=False)

    if request.method == 'POST':
        for labor_request in pending_call_times:
            response_key = f"response_{labor_request.id}"
            response = request.data.get(response_key)
            if response in ['yes', 'no']:
                labor_request.availability_response = response
                labor_request.responded_at = timezone.now()
                labor_request.save()
                if response == 'yes' and not labor_request.labor_requirement.fcfs_positions > 0 and not labor_request.is_reserved:
                    notif_message = f"{worker.name} Available for {event.event_name} - {labor_request.labor_requirement.call_time.name} - {labor_request.labor_requirement.labor_type.name}, Requires confirmation"
                    notify(labor_request.id, 'Available', notif_message)
                if response == 'yes' and labor_request.labor_requirement.fcfs_positions > 0 and not labor_request.is_reserved:
                    confirmed_count = LaborRequest.objects.filter(
                        labor_requirement=labor_request.labor_requirement,
                        confirmed=True).count()
                    if confirmed_count < labor_request.labor_requirement.fcfs_positions:
                        labor_request.confirmed = True
                        labor_request.save()
                        notif_message = f"{worker.name} confirmed for {event.event_name} - {labor_request.labor_requirement.call_time.name} - {labor_request.labor_requirement.labor_type.name}"
                        notify(labor_request.id, 'Confirmed', notif_message)
        return Response({'status': 'success'})

    # Serialize data
    confirmed_serializer = LaborRequestSerializer(confirmed_call_times, many=True)
    pending_serializer = LaborRequestSerializer(pending_call_times, many=True)
    available_serializer = LaborRequestSerializer(available_call_times, many=True)
    event_serializer = EventSerializer(event)
    worker_serializer = WorkerSerializer(worker)

    qr_code_data = None
    if confirmed_call_times:
        token, created = ClockInToken.objects.get_or_create(
            event=event,
            worker=worker,
            defaults={'expires_at': timezone.now() + timedelta(days=1), 'qr_sent': False}
        )
        clock_in_url = request.build_absolute_uri(reverse('worker_clock_in_out', args=[str(token.token)]))
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(clock_in_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        qr_code_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

    registration_link = f"/user/register/?phone={worker.phone_number}"

    context = {
        'event': event_serializer.data,
        'worker': worker_serializer.data,
        'confirmed_call_times': confirmed_serializer.data,
        'pending_call_times': pending_serializer.data,
        'available_call_times': available_serializer.data,
        'qr_code_data': qr_code_data,
        'registration_link': registration_link,
    }
    return Response(context)





>>>>>>> Stashed changes
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


