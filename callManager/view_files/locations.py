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
def location_profiles(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    profiles = LocationProfile.objects.filter(company=company)
    context = {'profiles': profiles, 'company': company}
    return render(request, 'callManager/location_profiles.html', context)

@login_required
def create_location_profile(request):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    if request.method == "POST":
        form = LocationProfileForm(request.POST)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.company = company
            profile.save()
            messages.success(request, "Location profile created successfully.")
            return redirect('location_profiles')
        else:
            messages.error(request, "Failed to create location profile.")
    else:
        initial = {
            'minimum_hours': company.minimum_hours,
            'meal_penalty_trigger_time': company.meal_penalty_trigger_time,
            'hour_round_up': company.hour_round_up,
        }
        form = LocationProfileForm(initial=initial)
    context = {'form': form, 'company': company}
    return render(request, 'callManager/create_location_profile.html', context)


@login_required
def edit_location_profile(request, pk):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    profile = get_object_or_404(LocationProfile, pk=pk, company=company)
    if request.method == "POST":
        form = LocationProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Location profile updated successfully.")
            return redirect('location_profiles')
        else:
            messages.error(request, "Failed to update location profile.")
    else:
        form = LocationProfileForm(instance=profile)
    context = {'form': form, 'profile': profile, 'company': company}
    return render(request, 'callManager/edit_location_profile.html', context)


@login_required
def delete_location_profile(request, pk):
    if not hasattr(request.user, 'manager'):
        return redirect('login')
    manager = request.user.manager
    company = manager.company
    profile = get_object_or_404(LocationProfile, pk=pk, company=company)
    if request.method == "POST":
        profile.delete()
        messages.success(request, f"Location profile '{profile.name}' deleted successfully.")
        return redirect('location_profiles')
    messages.error(request, "Invalid request method.")
    return redirect('location_profiles')

