import json
from django.urls import reverse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import Event, LaborRequest, LaborRequirement, ManagerInvitation, SentSMS
from api.serializers import CompanySerializer, EventSerializer
from django.conf import settings
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from callManager.views import log_sms


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
            registration_url = request.build_absolute_uri(reverse('register_manager', args=[str(invitation.token)]))
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
