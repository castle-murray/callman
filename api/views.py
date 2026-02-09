""" api views for react application to consume """
from django.shortcuts import get_object_or_404
from api.serializers import CompanySerializer, LaborTypeSerializer, LocationProfileSerializer, UserSerializer
from callManager.models import (
        LaborType,
        LocationProfile,
        PasswordResetToken,
        )
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from datetime import timedelta
from django.utils import timezone
from callManager.utils.email import send_custom_email
from api.utils import frontend_url
import json
import logging
from django.conf import settings

from callman.settings import CORS_ALLOW_ALL_ORIGINS

logger = logging.getLogger(__name__)


    
@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login_view(request):
    logger.info(f"{CORS_ALLOW_ALL_ORIGINS}")
    if request.method == "POST":
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            token, created = Token.objects.get_or_create(user=user)
            return JsonResponse({
                'status': 'success', 
                'token': token.key,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email
                }
            })
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid credentials'}, status=401)



@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def logout(request):
    request.user.auth_token.delete()
    return Response({'status': 'success'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def forgot_password(request):
    email = request.data.get('email', '').strip()
    user = User.objects.filter(email=email).first()
    if user:
        token = PasswordResetToken.objects.create(
            user=user,
            expires_at=timezone.now() + timedelta(hours=1)
        )
        reset_url = frontend_url(request, f"/reset-password/{token.token}")
        send_custom_email(
            subject="CallMan Password Reset",
            to_email=user.email,
            template_name='callManager/emails/password_reset_email.html',
            context={'reset_url': reset_url, 'user': user}
        )
    return Response({'status': 'success', 'message': 'If an account with that email exists, a password reset link has been sent.'})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_password(request, token):
    try:
        reset_token = PasswordResetToken.objects.get(
            token=token,
            expires_at__gt=timezone.now(),
            used=False
        )
    except PasswordResetToken.DoesNotExist:
        return Response({'status': 'error', 'message': 'Invalid or expired reset link.'}, status=400)

    new_password = request.data.get('new_password', '')
    confirm_password = request.data.get('confirm_password', '')

    if not new_password or len(new_password) < 8:
        return Response({'status': 'error', 'message': 'Password must be at least 8 characters.'}, status=400)
    if new_password != confirm_password:
        return Response({'status': 'error', 'message': 'Passwords do not match.'}, status=400)

    reset_token.user.set_password(new_password)
    reset_token.user.save()
    reset_token.used = True
    reset_token.save()
    return Response({'status': 'success', 'message': 'Your password has been reset successfully.'})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def user_info(request):
    user = request.user
    isManager = False
    isSteward = False
    isAdministrator = False
    isOwner = False
    isWorker = False
    if hasattr(user, 'manager'):
        isManager = True
    if hasattr(user, 'steward'):
        isSteward = True
    if hasattr(user, 'administrator'):
        isAdministrator = True
    if hasattr(user, 'owner'):
        isOwner = True
    if hasattr(user, 'worker'):
        isWorker = True
    
    slug = user.profile.slug if hasattr(user, 'profile') else user.username
    has_userprofile = hasattr(user, 'profile')

    context = {
        'user': {
            'slug': slug,
            'isManager': isManager,
            'isSteward': isSteward,
            'isAdministrator': isAdministrator,
            'isOwner': isOwner,
            'isWorker': isWorker,
            'has_userprofile': has_userprofile,
        }
    }
    return Response(context)


@api_view(['GET', 'POST'])
def skills_list(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    skills = LaborType.objects.filter(company=company).order_by('name')
    if request.method == "GET":
        serializer = LaborTypeSerializer(skills, many=True)
        return Response(serializer.data)
    elif request.method == "POST":
        action = request.data.get('action')
        if action == 'add':
            name = request.data.get('name')
            if not name:
                return Response({'status': 'error', 'message': 'Name is required'}, status=400)
            skill, created = LaborType.objects.get_or_create(company=company, name=name)
            if not created:
                return Response({'status': 'error', 'message': 'Skill already exists'}, status=400)
            serializer = LaborTypeSerializer(skill)
            return Response(serializer.data, status=201)
        elif action == 'delete':
            skill_id = request.data.get('skill_id')
            if not skill_id:
                return Response({'status': 'error', 'message': 'Skill ID is required'}, status=400)
            skill = get_object_or_404(LaborType, id=skill_id, company=company)
            skill.delete()
            return Response({'status': 'success', 'message': 'Skill deleted'}, status=200)
        elif action == 'edit':
            skill_id = request.data.get('skill_id')
            if not skill_id:
                return Response({'status': 'error', 'message': 'Skill ID is required'}, status=400)
            name = request.data.get('name')
            if not name:
                return Response({'status': 'error', 'message': 'Name is required'}, status=400)
            if LaborType.objects.filter(company=company, name=name).exclude(id=skill_id).exists():
                return Response({'status': 'error', 'message': 'Skill already exists'}, status=400)
            skill = get_object_or_404(LaborType, id=skill_id, company=company)
            skill.name = name
            skill.save()
            serializer = LaborTypeSerializer(skill)
            return Response(serializer.data, status=200)    
        else:
            return Response({'status': 'error', 'message': 'Invalid action'}, status=400)


@api_view(['GET', 'POST', 'DELETE', 'PATCH'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def location_profiles(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    if request.method == "GET":
        location_profiles = company.location_profiles.all()
        serialized_company = CompanySerializer(company)
        serializer = LocationProfileSerializer(location_profiles, many=True)
        context = {
            'location_profiles': serializer.data,
            'company': serialized_company.data
        }
        return Response(context)
    elif request.method == "POST":
        formdata = request.data
        serializer = LocationProfileSerializer(data=formdata)
        if serializer.is_valid():
            serializer.validated_data['company'] = company
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == "DELETE":
        data = json.loads(request.body)
        location_profile = get_object_or_404(LocationProfile, id=data.get('location_id'), company=company)
        if location_profile.events.exists():
            return Response({'status': 'error', 'message': 'Location profile is in use'}, status=400)
        location_profile.delete()
        return Response({'status': 'success'}, status=204)
    elif request.method == "PATCH":
        data = json.loads(request.body)
        location_profile = get_object_or_404(LocationProfile, id=data.get('location_id'), company=company)
        formdata = request.data
        serializer = LocationProfileSerializer(location_profile, data=formdata, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
