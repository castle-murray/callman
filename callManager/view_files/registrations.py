
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


def register_owner(request, token):
    invitation = get_object_or_404(OwnerInvitation, token=token, used=False)
    if request.method == "POST":
        form = OwnerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.first_name = form.cleaned_data['first_name']
            user.phone_number = invitation.phone
            user.save()
            company = Company.objects.create(
                name=form.cleaned_data['company_name'],
                name_short=form.cleaned_data['company_short_name'],
                email=form.cleaned_data['email'], 
                phone_number=invitation.phone,
                # Add other required Company fields with defaults or from form if needed
            )
            Owner.objects.create(user=user, company=company)
            invitation.used = True
            invitation.save()
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            if user is not None:
                manager = Manager.objects.create(user=user, company=company)
            login(request, user)
            messages.success(request, "Registration successful. Welcome to Callman.")
            return redirect('manager_dashboard')
    else:
        form = OwnerRegistrationForm()
    context = {'form': form, 'invitation': invitation}
    return render(request, 'callManager/register_owner.html', context)


def register_manager(request, token):
    invitation = get_object_or_404(ManagerInvitation, token=token, used=False)
    if request.method == "POST":
        form = ManagerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.first_name = form.cleaned_data['first_name']
            user.phone_number = invitation.phone
            user.save()
            Manager.objects.create(user=user, company=invitation.company)
            invitation.used = True
            invitation.save()
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, "Registration successful. You are now a manager.")
            return redirect('manager_dashboard')
    else:
        form = ManagerRegistrationForm()
    context = {'form': form, 'invitation': invitation}
    return render(request, 'callManager/register_manager.html', context)


def register_steward(request, token):
    invitation = get_object_or_404(StewardInvitation, token=token, used=False)
    if request.method == "POST":
        form = WorkerRegistrationForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            workers = Worker.objects.filter(phone_number=phone_number)
            if not workers.exists() or invitation.worker not in workers:
                messages.error(request, "No worker found with this phone number or phone number does not match invitation.")
                return render(request, 'callManager/register_steward.html', {'form': form, 'invitation': invitation})
            already_registered = workers.filter(user__isnull=False)
            if already_registered.exists():
                messages.error(request, "One or more workers with this phone number are already registered with a user account.")
                return render(request, 'callManager/register_steward.html', {'form': form, 'invitation': invitation})
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.save()
            Steward.objects.create(user=user, company=invitation.company)
            workers.update(user=user)
            invitation.used = True
            invitation.save()
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, "Registration successful. You are now a steward.")
            return redirect('user_profile')
    else:
        form = WorkerRegistrationForm(initial={'phone_number': invitation.worker.phone_number})
    context = {'form': form, 'invitation': invitation}
    return render(request, 'callManager/register_steward.html', context)


def registration_success(request):
    return render(request, 'callManager/registration_success.html')


def user_registration(request):
    phone_number = request.GET.get('phone', '')
    if request.method == "POST":
        form = WorkerRegistrationForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']
            workers = Worker.objects.filter(phone_number=phone_number)
            if not workers.exists():
                messages.error(request, "No workers found with this phone number.")
                return render(request, 'callManager/user_registration.html', {'form': form, 'phone_number': phone_number})
            already_registered = workers.filter(user__isnull=False)
            if already_registered.exists():
                messages.error(request, "One or more workers with this phone number are already registered with a user account.")
                return render(request, 'callManager/user_registration.html', {'form': form, 'phone_number': phone_number})
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.save()
            workers.update(user=user)
            # Send welcome email
            send_custom_email(
                subject="Welcome to CallMan!",
                to_email=user.email,
                template_name='callManager/emails/welcome_email.html',
                context={'user': user}
            )
            user = authenticate(username=form.cleaned_data['username'], password=form.cleaned_data['password1'])
            login(request, user)
            messages.success(request, "Registration successful. You are now a worker.")
            return redirect('user_profile')
    else:
        form = WorkerRegistrationForm(initial={'phone_number': phone_number})
    context = {'form': form, 'phone_number': phone_number}
    return render(request, 'callManager/user_registration.html', context)

