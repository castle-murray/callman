from datetime import timedelta
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import LaborRequest
from callManager.models import SentSMS

@api_view(['GET']) 
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def sms_count(request):
    user = request.user
    if hasattr(user, 'manager') and not hasattr(user, 'administrator'):
        manager = user.manager
        company = manager.company
        ## messages sent in the last 30 days
        sent_messages = SentSMS.objects.filter(
            company=company,
            datetime_sent__gte=timezone.now() - timedelta(days=30)
            ).count()
        return Response({'count': sent_messages})
    elif hasattr(user, 'administrator'):
        sent_messages = SentSMS.objects.filter(
            datetime_sent__gte=timezone.now() - timedelta(days=30)
            ).count()
        return Response({'count': sent_messages})
    else:
        return Response({'count': 0})
