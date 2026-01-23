from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import AltPhone, UserProfile, Worker
from api.serializers import WorkerSerializer

def valid_phone_number(phone_number):
    phone_number = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').replace('.', '')
    if phone_number.startswith('+1') and len(phone_number) == 12:
        return phone_number
    if len(phone_number) == 10:
        phone_number = f"+1{phone_number}"
    elif len(phone_number) == 11 and phone_number.startswith('1'):
        phone_number = f"+{phone_number}"
    elif len(phone_number) < 10:
        return None
    return phone_number

@api_view(['GET', 'POST', 'PATCH', 'DELETE', 'PUT'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def list_workers(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    company = user.manager.company
    if request.method == "POST":
        name = request.data.get('name')
        phone_number = request.data.get('phone_number')
        if Worker.objects.filter(phone_number=phone_number, company=company).exists():
            return Response({'status': 'error', 'message': 'Worker with this phone number already exists'}, status=400)
        if not name or not phone_number:
            return Response({'status': 'error', 'message': 'Name and phone number are required'}, status=400)
        worker = Worker.objects.create(name=name, phone_number=phone_number, company=company)
        worker_user = UserProfile.objects.filter(phone_number=phone_number).first()
        if worker_user:
            worker.user = worker_user.user
            worker.save()
        else:
            registration_token = RegistrationToken.objects.create(worker=worker)
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        return Response(serializer.data, status=201)
    elif request.method == "PATCH":
        phone_number = valid_phone_number(request.data.get('phone_number'))
        if not phone_number:
            return Response({'status': 'error', 'message': 'Invalid phone number'}, status=400)
        
        worker_id = request.data.get('id')
        worker = get_object_or_404(Worker, id=worker_id, company=company)
        worker.name = request.data.get('name', worker.name)
        worker.phone_number = phone_number or worker.phone_number
        worker.save()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        return Response(serializer.data, status=200)
    elif request.method == "PUT":
        phone_number = valid_phone_number(request.data.get('phone_number'))
        label = request.data.get('label')
        if not phone_number:
            return Response({'status': 'error', 'message': 'Invalid phone number'}, status=400)
        worker_id = request.data.get('id')
        worker = get_object_or_404(Worker, id=worker_id, company=user.manager.company)
        alt_phone = AltPhone.objects.create(worker=worker, phone_number=phone_number, label=request.data.get('label', None))
        alt_phone.save()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        return Response(serializer.data, status=200)
        
    elif request.method == "GET":
        workers = Worker.objects.filter(company=user.manager.company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        return Response(serializer.data)

