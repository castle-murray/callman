
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
def user_profile(request):
    workers = request.user.workers.all()
    if not workers.exists():
        messages.error(request, "You are not currently associated with any company accounts. Please contact your manager.")
        return redirect('login')
    labor_requests = LaborRequest.objects.filter(worker__user=request.user).select_related(
        'labor_requirement__call_time__event'
    ).order_by('labor_requirement__call_time__date')
    context = {'labor_requests': labor_requests, 'workers': workers}
    return render(request, 'callManager/user_profile.html', context)


def auto_login(request, token):
    try:
        login_token = OneTimeLoginToken.objects.get(
            token=token,
            expires_at__gt=timezone.now(),
            used=False
        )
        login_token.used = True
        login_token.save()
        login(request, login_token.user)
        return redirect('import_workers')
    except OneTimeLoginToken.DoesNotExist:
        messages.error(request, "Invalid or expired login token.")
        return redirect('login')

def reset_password(request, token):
    try:
        reset_token = PasswordResetToken.objects.get(
            token=token,
            expires_at__gt=timezone.now(),
            used=False
        )
        if request.method == "POST":
            form = SetPasswordForm(user=reset_token.user, data=request.POST)
            if form.is_valid():
                form.save()
                reset_token.used = True
                reset_token.save()
                user = authenticate(username=reset_token.user.username, password=form.cleaned_data['new_password1'])
                login(request, user)
                messages.success(request, "Your password has been reset successfully.")
                return redirect('manager_dashboard')
        else:
            form = SetPasswordForm(user=reset_token.user)
    except PasswordResetToken.DoesNotExist:
        messages.error(request, "Invalid or expired password reset link.")
        form = None
    return render(request, 'callManager/reset_password.html', {'form': form})

def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get('email', '').strip()
        user = User.objects.filter(email=email).first()
        if user:
            # Create a password reset token
            token = PasswordResetToken.objects.create(
                user=user,
                expires_at=timezone.now() + timedelta(hours=1)
            )
            reset_url = request.build_absolute_uri(reverse('reset_password', args=[str(token.token)]))
            email_success = send_custom_email(
                subject="CallMan Password Reset",
                to_email=user.email,
                template_name='callManager/emails/password_reset_email.html',
                context={'reset_url': reset_url, 'user': user}
            )
            if email_success:
                messages.success(request, "A password reset link has been sent to your email.")
            else:
                messages.error(request, "Failed to send reset link. Please try again.")
        else:
            messages.error(request, "No user found with this email address.")
        return render(request, 'callManager/forgot_password.html')
    return render(request, 'callManager/forgot_password.html')

class CustomLoginView(LoginView):
    template_name = 'callManager/login.html'
    
    def get_success_url(self):
        user = self.request.user
        if hasattr(user, 'steward'):
            return reverse('steward_dashboard')
        elif hasattr(user, 'manager'):
            return reverse('manager_dashboard')
        else:
            return reverse('index')

