from django.contrib.auth.models import User
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from api.utils import frontend_url


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def invite_owner(request):
    user = request.user
    if not hasattr(user, 'administrator'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    if request.method == "POST":
        data = json.loads(request.body)
        phone = data.get('phone')
        if phone:
            invitation = OwnerInvitation.objects.create(phone=phone)
            registration_url = frontend_url(request, f"/owner/register/{invitation.token}/")
            send_message(f'You are invited to join Callman. Use the following link to register:\n{registration_url}', phone)
