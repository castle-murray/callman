
#models
from callManager.models import (
        LaborRequest,
        OneTimeLoginToken,
        PasswordResetToken,
        )

# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import LoginView
from callManager.utils.email import send_custom_email

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

