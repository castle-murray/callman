from django.contrib.auth.models import User
from django.utils import timezone
from callManager.models import UserProfile, LaborRequest, Worker, WorkerRegistrationToken
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import authentication_classes, permission_classes
from api.serializers import WorkerSerializer, LaborRequestSerializer
import random
import string
from datetime import timedelta
from callManager.views import send_message


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def start_user_registration(request):
    phone = request.data.get('phone')
    if not phone:
        return Response({'message': 'Phone number is required'}, status=status.HTTP_400_BAD_REQUEST)

    worker = Worker.objects.filter(phone_number=phone).first()
    if not worker:
        return Response({'message': 'No worker found with this phone number'}, status=status.HTTP_404_NOT_FOUND)

    verification_code = ''.join(random.choices(string.digits, k=6))
    token = WorkerRegistrationToken.objects.create(
        worker=worker,
        verification_code=verification_code,
        expires_at=timezone.now() + timedelta(hours=1)
    )
    # Send SMS
    send_message(f"Your verification code for CallMan registration is {verification_code}", worker, company=worker.company)

    return Response({'token': str(token.token), 'message': 'Verification code sent'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def user_registration(request):
    data = request.data
    username = data.get('username')
    phone = data.get('phone')
    email = data.get('email')
    password = data.get('password')
    token_str = data.get('token')
    verification_code = data.get('verification_code')

    if not all([username, phone, email, password, token_str, verification_code]):
        return Response({'message': 'All fields are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token_obj = WorkerRegistrationToken.objects.get(token=token_str, verification_code=verification_code, used=False)
        if token_obj.is_expired():
            return Response({'message': 'Verification code expired'}, status=status.HTTP_400_BAD_REQUEST)
        if token_obj.worker.phone_number != phone:
            return Response({'message': 'Phone number does not match'}, status=status.HTTP_400_BAD_REQUEST)
        token_obj.used = True
        token_obj.save()
    except WorkerRegistrationToken.DoesNotExist:
        return Response({'message': 'Invalid token or verification code'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({'message': 'User with this username already exists'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response({'message': 'User with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password
    )
    UserProfile.objects.create(user=user, phone_number=phone)

    # Link to existing Worker
    token_obj.worker.user = user
    token_obj.worker.save()

    return Response({'message': 'User created successfully'}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def user_profile(request):
    user = request.user
    phone_number = user.profile.phone_number
    workers = Worker.objects.filter(phone_number=phone_number)
    for worker in workers:
        if not worker.user == user:
            worker.user = user
            worker.save()
    labor_requests = LaborRequest.objects.filter(worker__user=user).select_related(
        'labor_requirement__call_time__event'
    ).order_by('labor_requirement__call_time__date')

    confirmed = labor_requests.filter(confirmed=True)
    upcoming = labor_requests.filter(labor_requirement__call_time__date__gte=timezone.now().date(), sms_sent=True).order_by('labor_requirement__call_time__call_unixtime')
    past = confirmed.filter(labor_requirement__call_time__date__lt=timezone.now().date(), sms_sent=True)

    worker_serializer = WorkerSerializer(workers, many=True)
    labor_request_serializer = LaborRequestSerializer(labor_requests, many=True)
    upcoming_serializer = LaborRequestSerializer(upcoming, many=True)
    past_serializer = LaborRequestSerializer(past, many=True)

    context = {
        'workers': worker_serializer.data,
        'labor_requests': labor_request_serializer.data,
        'upcoming': upcoming_serializer.data,
        'past': past_serializer.data,
    }
    return Response(context)
