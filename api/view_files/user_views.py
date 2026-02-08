from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.utils import timezone
from callManager.models import UserProfile, LaborRequest, Steward, Worker, RegistrationToken
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


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def resolve_steward_token(request, token):
    reg_token = get_object_or_404(RegistrationToken, token=token)
    if reg_token.used:
        return Response({'message': 'Token already used'}, status=status.HTTP_400_BAD_REQUEST)
    worker = reg_token.worker
    return Response({
        'phone': worker.phone_number,
        'token': str(reg_token.token),
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def start_user_registration(request):
    phone = request.data.get('phone')
    registration_token = request.data.get('token')
    print(request.data)
    print(registration_token)
    if len(phone) == 10:
        phone = f"+1{phone}"
    elif len(phone) == 11 and phone[0] == '1':
        phone = f"+{phone[1:]}"
    elif len(phone) < 10:
        return Response({'message': 'Phone number is too short'}, status=status.HTTP_400_BAD_REQUEST)
    if not phone:
        return Response({'message': 'Phone number is required'}, status=status.HTTP_400_BAD_REQUEST)
    worker = Worker.objects.filter(phone_number=phone).first()
    if not worker:
        return Response({'message': 'No worker found with this phone number'}, status=status.HTTP_404_NOT_FOUND)
    token = get_object_or_404(RegistrationToken, token=registration_token)
    token.save()
    # Send SMS
    verification_code = token.verification_code
    message = f"Your verification code is: {verification_code}"
    send_message(message, worker, None, None)

    return Response({'message': 'Verification code sent', 'token': str(token.token)}, status=status.HTTP_200_OK)


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

    print(token_str)

    if not all([username, phone, email, password, token_str, verification_code]):
        return Response({'message': 'All fields are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token_obj = get_object_or_404(RegistrationToken, token=token_str)
        
        if token_obj.used:
            return Response({'message': 'Token already used'}, status=status.HTTP_400_BAD_REQUEST)
        elif token_obj.veri_expires_at < timezone.now():
            return Response({'message': 'Verification code expired'}, status=status.HTTP_400_BAD_REQUEST)
        elif token_obj.verification_code != verification_code:
            return Response({'message': 'Invalid verification code'}, status=status.HTTP_400_BAD_REQUEST)
        token_obj.used = True
        token_obj.save()
    except RegistrationToken.DoesNotExist:
        return Response({'message': 'Invalid token or verification code'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({'message': 'User with this username already exists'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response({'message': 'User with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )
    UserProfile.objects.create(user=user, phone_number=phone)

    # Link to existing Worker
    worker = token_obj.worker
    worker.user = user
    worker.save()

    # Auto-create Steward if worker was flagged
    if worker.is_steward and worker.company:
        if not hasattr(user, 'steward'):
            Steward.objects.create(user=user, company=worker.company)

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
    companies = []
    for worker in workers:
        if worker.company:
            companies.append(worker.company.name)
    upcoming_serializer = LaborRequestSerializer(upcoming, many=True)
    past_serializer = LaborRequestSerializer(past, many=True)

    context = {
        'workers': worker_serializer.data,
        'companies': companies,
        'labor_requests': labor_request_serializer.data,
        'upcoming': upcoming_serializer.data,
        'past': past_serializer.data,
    }
    return Response(context)
