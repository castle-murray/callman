#models
from callManager.models import LocationProfile
#forms
from callManager.forms import LocationProfileForm

# Django imports
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

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

