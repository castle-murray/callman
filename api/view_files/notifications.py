from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import Notifications


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def notifications(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company
    notifications = Notifications.objects.filter(company=company).select_related('labor_requirement').order_by('-sent_at')
    data = [{
        'id': n.id,
        'response': n.response,
        'message': n.message,
        'sent_at': n.sent_at,
        'read': n.read,
        'event': n.event.event_name,
        'call_time': n.call_time.name if n.call_time else None,
        'labor_requirement_slug': n.labor_requirement.slug if n.labor_requirement else None,
    } for n in notifications]
    return Response(data)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_as_read(request, notification_id):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company

    try:
        notification = Notifications.objects.get(id=notification_id, company=company)
        notification.read = True
        notification.save()
        return Response({'status': 'success'})
    except Notifications.DoesNotExist:
        return Response({'status': 'error', 'message': 'Notification not found'}, status=404)


@api_view(['DELETE'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_notification(request, notification_id):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company

    try:
        notification = Notifications.objects.get(id=notification_id, company=company)
        notification.delete()
        return Response({'status': 'success'})
    except Notifications.DoesNotExist:
        return Response({'status': 'error', 'message': 'Notification not found'}, status=404)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def clear_all_notifications(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company

    Notifications.objects.filter(company=company).delete()
    return Response({'status': 'success'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def clear_read_notifications(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    manager = user.manager
    company = manager.company

    Notifications.objects.filter(company=company, read=True).delete()
    return Response({'status': 'success'})