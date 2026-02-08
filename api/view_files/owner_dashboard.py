import json
from django.urls import reverse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import Event, LaborRequest, LaborRequirement, ManagerInvitation, RegistrationToken, SentSMS, Steward, StewardInvitation, UserProfile, Worker
from api.serializers import CompanySerializer, EventSerializer
from django.conf import settings
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from callManager.views import log_sms
from api.utils import frontend_url


@api_view(['GET', 'PATCH'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def owner_dashboard(request):
    user = request.user
    if not hasattr(user, 'owner'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    owner = user.owner
    company = owner.company
    if request.method == "GET":
        serialized_company = CompanySerializer(company)
        return Response(serialized_company.data)
    elif request.method == "PATCH":
        formdata = request.data
        phone_number = formdata.get('phone_number')
        if phone_number:
            phone_number = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('.', '')
            if len(phone_number) == 10:
                phone_number = f"+1{phone_number}"
            elif len(phone_number) == 11 and phone_number.startswith('1'):
                phone_number = f"+{phone_number}"
            elif len(phone_number) < 10:
                phone_number = None
        if phone_number: 
            formdata['phone_number'] = phone_number
        else:
            formdata.pop('phone_number', None)
        serializer = CompanySerializer(company, data=formdata, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    else:
        return Response({'status': 'error', 'message': 'Invalid request method'}, status=400)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def send_manager_invite(request):
    user = request.user
    if not hasattr(user, 'owner'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    owner = user.owner
    company = owner.company
    if request.method == "POST":
        data = json.loads(request.body)
        phone = data.get('phone')
        if phone:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
            invitation = ManagerInvitation.objects.create(company=company, phone=phone)
            registration_url = frontend_url(request, f"/manager/register/{invitation.token}/")
            message_body = f'You are invited to become a manager for {company.name}. Register: {registration_url}'
            if settings.TWILIO_ENABLED == 'enabled' and client:
                try:
                    client.messages.create(
                        body=message_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=phone)
                    log_sms(company)
                except TwilioRestException as e:
                    print(f"Failed to send invitation: {str(e)}")
                return Response({'status': 'success', 'message': 'Invitation sent'}, status=200)
            else:
                log_sms(company)
                print(message_body)
        else:
            return Response({'status': 'error', 'message': 'No phone number provided'}, status=400)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def send_steward_invite(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    data = json.loads(request.body)
    phone = data.get('phone')
    name = data.get('name', '')
    if phone:
        phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('.', '')
        if len(phone) == 10:
            phone_number = f"+1{phone}"
        elif len(phone) == 11 and phone.startswith('1'):
            phone_number = f"+{phone}"
        else:
            phone_number = phone
        # Check for UserProfile with this phone
        try:
            user_profile = UserProfile.objects.get(phone_number=phone_number)
            user_obj = user_profile.user
            # Check if already steward
            if not hasattr(user_obj, 'steward'):
                Steward.objects.create(user=user_obj, company=company)
                return Response({'status': 'success', 'message': 'User made steward'}, status=200)
            else:
                return Response({'status': 'error', 'message': 'User is already a steward'}, status=400)
        except UserProfile.DoesNotExist:
            # Find or create worker, mark as steward, send registration link
            worker, _created = Worker.objects.get_or_create(
                phone_number=phone_number,
                company=company,
                defaults={'name': name}
            )
            if not _created and name:
                worker.name = name
            worker.is_steward = True
            worker.save()
            reg_token = RegistrationToken.objects.create(worker=worker)
            registration_url = frontend_url(request, f"/steward/register/{reg_token.token}/")
            message_body = f'You are invited to become a steward for {company.name}. Register: {registration_url}'
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
            if settings.TWILIO_ENABLED == 'enabled' and client:
                try:
                    client.messages.create(
                        body=message_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=phone_number)
                    log_sms(company)
                except TwilioRestException as e:
                    print(f"Failed to send invitation: {str(e)}")
                return Response({'status': 'success', 'message': 'Invitation sent'}, status=200)
            else:
                log_sms(company)
                print(message_body)
                return Response({'status': 'success', 'message': 'Invitation would be sent (SMS disabled)'}, status=200)
    else:
        return Response({'status': 'error', 'message': 'No phone number provided'}, status=400)
