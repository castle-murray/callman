from io import TextIOWrapper

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes, parser_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from callManager.models import AltPhone, LaborRequest, LaborType, UserProfile, Worker, RegistrationToken
from api.serializers import LaborTypeSerializer, WorkerSerializer

def valid_phone_number(phone_number):
    if not phone_number:
        return None
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
    labor_types = LaborType.objects.filter(company=company).order_by('name')
    labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
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
            registration_token.save()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        context = {
            'workers': serializer.data,
            'labor_types': labor_type_serializer.data,
        }
        return Response(context, status=201)
    elif request.method == "PATCH":
        if 'alt_id' in request.data:
            alt_id = request.data.get('alt_id')
            alt_phone = get_object_or_404(AltPhone, id=alt_id, worker__company=company)
            phone_number = valid_phone_number(request.data.get('phone_number'))
            if not phone_number:
                return Response({'status': 'error', 'message': 'Invalid phone number'}, status=400)
            alt_phone.phone_number = phone_number
            alt_phone.label = request.data.get('label', alt_phone.label)
            alt_phone.save()
        elif 'labor_types' in request.data:
            labor_type_ids = request.data.get('labor_types', [])
            labor_types = LaborType.objects.filter(id__in=labor_type_ids, company=company)
            worker = get_object_or_404(Worker, id=request.data.get('id'), company=company)
            worker.labor_types.set(labor_types)
            worker.save()
        else:
            phone_number = valid_phone_number(request.data.get('phone_number'))
            if not phone_number:
                return Response({'status': 'error', 'message': 'Invalid phone number'}, status=400)

            worker_id = request.data.get('id')
            worker = get_object_or_404(Worker, id=worker_id, company=company)
            worker.name = request.data.get('name', worker.name)
            worker.phone_number = phone_number or worker.phone_number
            if 'labor_types' in request.data:
                labor_type_ids = request.data.get('labor_types', [])
                worker.labor_types.set(labor_type_ids)
            worker.save()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        labor_types = LaborType.objects.filter(company=company)
        labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
        context = {
            'workers': serializer.data,
            'labor_types': labor_type_serializer.data,
        }
        return Response(context, status=200)
    elif request.method == "PUT":
        if 'make_primary' in request.data and request.data.get('make_primary'):
            worker_id = request.data.get('id')
            alt_id = request.data.get('alt_id')
            worker = get_object_or_404(Worker, id=worker_id, company=company)
            alt_phone = get_object_or_404(AltPhone, id=alt_id, worker=worker)
            old_primary = worker.phone_number
            worker.phone_number = alt_phone.phone_number
            worker.save()
            alt_phone.phone_number = old_primary
            alt_phone.label = ''
            alt_phone.save()
        else:
            phone_number = valid_phone_number(request.data.get('phone_number'))
            if not phone_number:
                return Response({'status': 'error', 'message': 'Invalid phone number'}, status=400)
            worker_id = request.data.get('id')
            worker = get_object_or_404(Worker, id=worker_id, company=company)
            alt_phone = AltPhone.objects.create(worker=worker, phone_number=phone_number, label=request.data.get('label', None))
            alt_phone.save()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        labor_types = LaborType.objects.filter(company=company)
        labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
        context = {
            'workers': serializer.data,
            'labor_types': labor_type_serializer.data,
        }
        return Response(context, status=200)
    elif request.method == "DELETE":
        worker_id = request.data.get('id')
        worker = get_object_or_404(Worker, id=worker_id, company=company)
        labor_requests = LaborRequest.objects.filter(worker=worker)
        if labor_requests.exists():
            return Response({'status': 'error', 'message': 'Worker has labor requests and cannot be deleted.'}, status=400)
        worker.delete()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        labor_types = LaborType.objects.filter(company=company)
        labor_type_serializer = LaborTypeSerializer(labor_types, many=True)
        context = {
            'workers': serializer.data,
            'labor_types': labor_type_serializer.data,
        }
        return Response(context, status=200)
    elif request.method == "DELETE":
        if 'alt_id' in request.data:
            alt_id = request.data.get('alt_id')
            alt_phone = get_object_or_404(AltPhone, id=alt_id, worker__company=company)
            alt_phone.delete()
        else:
            worker_id = request.data.get('id')
            worker = get_object_or_404(Worker, id=worker_id, company=company)
            # Check for work history or other conditions
            if worker.canceled_requests > 0 or worker.nocallnoshow > 0:
                return Response({'status': 'error', 'message': 'Cannot delete worker with work history'}, status=400)
            worker.delete()
        workers = Worker.objects.filter(company=company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        return Response(serializer.data, status=200)

    elif request.method == "GET":
        workers = Worker.objects.filter(company=user.manager.company).order_by('name')
        serializer = WorkerSerializer(workers, many=True)
        context = {
            'workers': serializer.data,
            'labor_types': labor_type_serializer.data,
        }
        return Response(context, status=200)





@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def worker_history(request, slug):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    company = user.manager.company
    worker = get_object_or_404(Worker, slug=slug, company=company)
    labor_requests = worker.labor_requests.filter(labor_requirement__call_time__event__company=company)
    confirmed_requests = labor_requests.filter(confirmed=True)
    declined_requests = labor_requests.filter(availability_response='no')
    ncns_requests = labor_requests.filter(availability_response='ncns')
    pending_requests = labor_requests.filter(availability_response__isnull=True)
    available_requests = labor_requests.filter(availability_response='yes', confirmed=False)

    from api.serializers import LaborRequestSerializer
    return Response({
        'worker': WorkerSerializer(worker).data,
        'confirmed_requests': LaborRequestSerializer(confirmed_requests, many=True).data,
        'declined_requests': LaborRequestSerializer(declined_requests, many=True).data,
        'ncns_requests': LaborRequestSerializer(ncns_requests, many=True).data,
        'pending_requests': LaborRequestSerializer(pending_requests, many=True).data,
        'available_requests': LaborRequestSerializer(available_requests, many=True).data,
    })


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def import_workers(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    company = user.manager.company

    vcf_file_obj = request.FILES.get('file')
    if not vcf_file_obj:
        return Response({'status': 'error', 'message': 'No file provided'}, status=400)
    if not vcf_file_obj.name.endswith('.vcf'):
        return Response({'status': 'error', 'message': 'File must be a .vcf file'}, status=400)

    vcf_file = TextIOWrapper(vcf_file_obj.file, encoding='utf-8')
    imported = 0
    skipped = 0
    errors = []
    current_name = None
    current_phones = []

    for line in vcf_file:
        line = line.strip()
        try:
            if line.startswith('END:VCARD'):
                if current_phones:
                    primary_phone = valid_phone_number(current_phones[0]['number'])
                    if not primary_phone:
                        errors.append(f"Invalid phone number for {current_name or 'Unnamed'}")
                        current_name = None
                        current_phones = []
                        continue
                    worker, created = Worker.objects.get_or_create(
                        phone_number=primary_phone,
                        company=company,
                        defaults={'name': current_name.strip() if current_name else 'Unnamed'},
                    )
                    if created:
                        imported += 1
                        for extra in current_phones[1:]:
                            alt_num = valid_phone_number(extra['number'])
                            if alt_num:
                                AltPhone.objects.get_or_create(
                                    worker=worker,
                                    phone_number=alt_num,
                                    defaults={'label': extra.get('label', '')},
                                )
                    else:
                        skipped += 1
                current_name = None
                current_phones = []
            elif line.startswith('FN:'):
                current_name = line[3:].strip()
            elif line.startswith('TEL'):
                # Parse label from TEL params: TEL;CELL:, TEL;HOME:, TEL;TYPE=CELL:, TEL;CELL;PREF:
                label = ''
                header, _, number = line.partition(':')
                params = header.split(';')[1:]  # everything after TEL
                for param in params:
                    p = param.upper().strip()
                    if p in ('PREF', 'VOICE', 'ENCODING=QUOTED-PRINTABLE'):
                        continue
                    if p.startswith('TYPE='):
                        label = param.split('=', 1)[1].strip()
                    elif not label:
                        label = param.strip()
                if number.strip():
                    current_phones.append({'number': number.strip(), 'label': label})
        except Exception:
            errors.append(f"Failed to import: {current_name or 'Unnamed'}")

    return Response({
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
    })


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def import_contacts_json(request):
    user = request.user
    if not hasattr(user, 'manager'):
        return Response({'status': 'error', 'message': 'Unauthorized'}, status=401)
    company = user.manager.company

    contacts = request.data.get('contacts', [])
    if not contacts:
        return Response({'status': 'error', 'message': 'No contacts provided'}, status=400)

    imported = 0
    skipped = 0
    errors = []

    for contact in contacts:
        name = contact.get('name', '').strip() or 'Unnamed'
        phone_numbers = contact.get('phone_numbers', [])
        # Backwards compat: single phone_number field
        if not phone_numbers and contact.get('phone_number'):
            phone_numbers = [{'phone_number': contact['phone_number']}]
        if not phone_numbers:
            errors.append(f"No phone number for {name}")
            continue
        primary = valid_phone_number(phone_numbers[0].get('phone_number', ''))
        if not primary:
            errors.append(f"Invalid phone number for {name}")
            continue
        try:
            worker, created = Worker.objects.get_or_create(
                phone_number=primary,
                company=company,
                defaults={'name': name},
            )
            if created:
                imported += 1
                for extra in phone_numbers[1:]:
                    alt_num = valid_phone_number(extra.get('phone_number', ''))
                    if alt_num:
                        AltPhone.objects.get_or_create(
                            worker=worker,
                            phone_number=alt_num,
                            defaults={'label': extra.get('label', '')},
                        )
            else:
                skipped += 1
        except Exception:
            errors.append(f"Failed to import: {name}")

    return Response({
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
    })
