
#models
from callManager.models import (
        Steward,
        Worker,
        Owner,
        OwnerInvitation,
        Manager,
        ManagerInvitation,
        Company,
        StewardInvitation,
        )
#forms
from callManager.forms import (
        WorkerRegistrationForm,
        OwnerRegistrationForm,
        ManagerRegistrationForm,
        )
# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login
from callManager.utils.email import send_custom_email

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

