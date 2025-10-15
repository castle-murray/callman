
#models
from time import sleep
from callManager.models import (
        CallTime,
        LaborRequest,
        Event,
        LaborRequirement,
        LaborType,
        OneTimeLoginToken,
        PasswordResetToken,
        Steward,
        TimeChangeConfirmation,
        Worker,
        TimeEntry,
        MealBreak,
        SentSMS,
        ClockInToken,
        Owner,
        OwnerInvitation,
        Manager,
        ManagerInvitation,
        Company,
        StewardInvitation,
        TemporaryScanner,
        LocationProfile,
        )
#forms
from callManager.forms import (
        CallTimeForm,
        CompanyHoursForm,
        LaborTypeForm,
        LaborRequirementForm,
        EventForm,
        WorkerForm,
        WorkerFormLite,
        WorkerImportForm,
        WorkerRegistrationForm,
        SkillForm,
        OwnerRegistrationForm,
        ManagerRegistrationForm,
        CompanyForm,
        LocationProfileForm,
        AddWorkerForm
        )
# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.http import base64
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, time, timedelta
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.contrib.messages import get_messages as django_get_messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import FileResponse
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from django.contrib.auth.views import LoginView
from callManager.utils import send_custom_email

# Twilio imports
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from twilio.twiml.messaging_response import MessagingResponse

# repotlab imports for PDF generation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import PageBreak, Table, TableStyle, Paragraph, SimpleDocTemplate, Table, TableStyle, Spacer, KeepTogether
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet

# other imports
import qrcode
from io import BytesIO, TextIOWrapper
import re
import random
import string
import uuid
from urllib.parse import urlencode, quote
from user_agents import parse

# posssibly imports
import pytz
import io

import logging

# Create a logger instance
logger = logging.getLogger('callManager')

@login_required
def create_labor_type(request):
    manager = request.user.manager
    if request.method == "POST":
        form = LaborTypeForm(request.POST)
        if form.is_valid():
            labor_type = form.save(commit=False)
            labor_type.company = manager.company
            labor_type.save()
            return redirect('labor_type_list')
    else:
        form = LaborTypeForm()
    return render(request, 'callManager/create_labor_type.html', {'form': form})

@login_required
def view_skills(request):
    manager = request.user.manager
    skills = LaborType.objects.filter(company=manager.company)
    if request.method == "POST":
        if 'delete_id' in request.POST:
            # check all events for labor requirements using this skill
            if LaborRequirement.objects.filter(labor_type__id=request.POST.get('delete_id')).exists():
                messages.error(request, "Cannot delete skill that is in use.")
                return redirect('view_skills')
            skill_id = request.POST.get('delete_id')
            skill = get_object_or_404(LaborType, id=skill_id, company=manager.company)
            skill.delete()
            messages.success(request, f"{skill.name} deleted")
            return redirect('view_skills')
        elif 'edit_id' in request.POST:
            skill_id = request.POST.get('edit_id')
            skill = get_object_or_404(LaborType, id=skill_id, company=manager.company)
            form = SkillForm(request.POST, instance=skill)
            if form.is_valid():
                form.save()
                return redirect('view_skills')
        elif 'add_skill' in request.POST:
            form = SkillForm(request.POST)
            if form.is_valid():
                skill = form.save(commit=False)
                skill.name = skill.name.title()
                if skill.name not in skills.values_list('name', flat=True):
                    skill.company = manager.company
                    skill.save()
                    messages.success(request, f"Skill {skill.name} added successfully.")
                    return redirect('view_skills')
                else:
                    messages.error(request, "Skill already exists.")
                    return redirect('view_skills')
    edit_forms = {skill.id: SkillForm(instance=skill) for skill in skills}
    add_form = SkillForm()
    context = {
        'skills': skills,
        'edit_forms': edit_forms,
        'add_form': add_form,
    }
    return render(request, 'callManager/view_skills.html', context)

@login_required
def view_workers(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    workers = Worker.objects.filter(company=company).order_by('name')
    search_query = request.GET.get('search', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    if search_query or skill_id:
        query = Q()
        if search_query:
            query &= Q(name__icontains=search_query) | Q(phone_number__icontains=search_query)
        if skill_id:
            query &= Q(labor_types__id=skill_id)
        workers = workers.filter(query)
    paginator = Paginator(workers, int(request.GET.get('per_page', manager.per_page_preference)))
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    if request.method == "POST":
        if 'add_worker' in request.POST:
            form = WorkerForm(request.POST, company=manager.company)
            if form.is_valid():
                if Worker.objects.filter(phone_number=form.cleaned_data['phone_number'], company=manager.company).exists():
                    messages.error(request, "Worker with this phone number already exists.")
                    return redirect('view_workers')
                worker = form.save(commit=False)
                if worker.phone_number.startswith('1') and len(worker.phone_number) == 11:
                    worker.phone_number = f"+{worker.phone_number}"
                elif not worker.phone_number.startswith('+') and len(worker.phone_number) == 10:
                    worker.phone_number = f"+1{worker.phone_number}"
                worker.save()
                worker.add_company(manager.company)
                messages.success(request, f"Worker {worker.name} added successfully.")
                query_params = {}
                if page_number != '1':
                    query_params['page'] = page_number
                if search_query:
                    query_params['search'] = search_query
                if skill_id:
                    query_params['skill'] = skill_id
                redirect_url = reverse('view_workers')
                if query_params:
                    redirect_url += '?' + urlencode(query_params)
                return redirect(redirect_url)
            else:
                messages.error(request, "Failed to add worker. Please check the form errors.")
    form = WorkerForm(company=manager.company)
    labor_types = LaborType.objects.filter(company=manager.company)
    context = {
        'workers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'skill_id': skill_id,
        'add_form': form,
        'labor_types': labor_types}
    return render(request, 'callManager/view_workers.html', context)

@login_required
def increment_nocallnoshow(request, worker_id):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    worker = get_object_or_404(Worker, id=worker_id)
    worker.nocallnoshow += 1
    worker.save()
    form = WorkerForm(instance=worker, company=request.user.manager.company)
    context = {
        'form': form,
        'worker': worker,
    }
    return render(request, 'callManager/nocallnoshow_partial.html', context)

@login_required
def decrement_nocallnoshow(request, worker_id):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    worker = get_object_or_404(Worker, id=worker_id)
    if worker.nocallnoshow > 0:  # Prevent negative values
        worker.nocallnoshow -= 1
        worker.save()
    form = WorkerForm(instance=worker, company=request.user.manager.company)
    context = {
        'form': form,
        'worker': worker,
    }
    return render(request, 'callManager/nocallnoshow_partial.html', context)

@login_required
def edit_worker(request, worker_id):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    worker = get_object_or_404(Worker, id=worker_id)
    if request.method == "POST":
        form = WorkerForm(request.POST, instance=worker, company=manager.company)
        if form.is_valid():
            form.save()
            return redirect('view_workers')
    else:
        form = WorkerForm(instance=worker, company=manager.company)
    context = {
        'form': form,
        'worker': worker,
    }
    return render(request, 'callManager/edit_worker.html', context)

@login_required
def import_workers(request):
    user_agent = parse(request.META.get('HTTP_USER_AGENT', ''))
    manager = request.user.manager
    is_mobile = user_agent.is_mobile or user_agent.is_tablet
    qr_url = None
    if not is_mobile:
        token = OneTimeLoginToken.objects.create(
                user=request.user,
                expires_at=timezone.now() + timedelta(hours=1)
                )
        qr_url = request.build_absolute_uri(reverse('auto_login', args=[str(token.token)]))
    if request.method == "POST":
        form = WorkerImportForm(request.POST, request.FILES)
        if form.is_valid():
            vcf_file = TextIOWrapper(request.FILES['file'].file, encoding='utf-8')
            imported = 0
            errors = 0
            current_name = None
            current_phone = None
            for i, line in enumerate(vcf_file):
                line = line.strip()
                try:
                    if line.startswith('END:VCARD'):
                        if current_name or current_phone:
                            if current_phone:
                                current_phone = current_phone.replace(' ', '').replace('-', '')
                                if current_phone.startswith('1') and len(current_phone) == 11:
                                    current_phone = f"+{current_phone}"
                                elif not current_phone.startswith('+') and len(current_phone) == 10:
                                    current_phone = f"+1{current_phone}"
                                elif len(current_phone) < 10:
                                    messages.error(request, f"Invalid phone number: {current_phone}")
                                    continue
                            worker, created = Worker.objects.get_or_create(
                                phone_number=current_phone,
                                company=manager.company,
                                defaults={'name': current_name.strip() if current_name else None})
                            if created:
                                imported += 1
                        current_name = None
                        current_phone = None
                    elif line.startswith('FN:'):
                        current_name = line[3:].strip()
                    elif line.startswith('TEL'):
                        parts = line.split(':')
                        if len(parts) > 1:
                            current_phone = parts[-1].strip()
                except Exception:
                    error_msg = f"Failed to import: {current_name or 'Unnamed'}, {current_phone or 'No phone'}"
                    messages.error(request, error_msg)
                    errors += 1
            messages.success(request, f"Imported {imported} workers.")
            if errors:
                messages.warning(request, f"Encountered {errors} import errors.")
            return render(request, 'callManager/import_workers.html', {'form': form, 'qr_url': qr_url, 'is_mobile': is_mobile})
    else:
        form = WorkerImportForm()
    return render(request, 'callManager/import_workers.html', {'form': form, 'qr_url': qr_url, 'is_mobile': is_mobile})

@login_required
def htmx_add_worker(request, labor_requirement_slug):
    form = WorkerFormLite(request.POST)
    labor_requirement = get_object_or_404(LaborRequirement, slug=labor_requirement_slug)
    return render(request, 'callManager/add_worker_partial.html', {'form': form, 'labor_requirement_slug': labor_requirement.slug})
        

@login_required
def search_workers(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    workers = Worker.objects.filter(company=manager.company).distinct().order_by('name')
    search_query = request.GET.get('search', '').strip()
    skill_id = request.GET.get('skill', '').strip()
    if search_query or skill_id:
        query = Q()
        if search_query:
            query &= Q(name__icontains=search_query) | Q(phone_number__icontains=search_query)
        if skill_id:
            query &= Q(labor_types__id=skill_id)
        workers = workers.filter(query)
    per_page = request.GET.get('per_page', '')
    if not per_page or not per_page.isdigit():
        per_page = manager.per_page_preference
    else:
        per_page = int(per_page)
    paginator = Paginator(workers, per_page)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    context = {
        'workers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'skill_id': skill_id,
        'per_page': per_page,
        }
    return render(request, 'callManager/workers_list_partial.html', context)

@login_required
def delete_worker(request, slug):
    if request.method == "DELETE":
        worker = get_object_or_404(Worker, slug=slug)
        worker_name = worker.name or "Unnamed Worker"
        labor_requests = LaborRequest.objects.filter(worker=worker)
        if labor_requests:
            messages.error(request, "Worker has labor requests and cannot be deleted.")
        else:
            worker.delete()
            messages.success(request, f"{worker_name} deleted.")
        return render(request, "callManager/messages_partial.html")

