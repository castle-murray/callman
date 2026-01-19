from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import Worker
from api.serializers import WorkerSerializer

@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def list_workers(request):
    user = request.user
    if hasattr(user, 'manager'):
        workers = Worker.objects.filter(company=user.manager.company).order_by('name')
    else:
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    serializer = WorkerSerializer(workers, many=True)
    return Response(serializer.data)

