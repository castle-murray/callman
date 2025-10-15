#models
from time import sleep
from callManager.models import (
        LaborRequest,
        Event,
        LaborRequirement,
        SentSMS,
        OwnerInvitation,
        )
# Django imports
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Sum, Q, Case, When, IntegerField, Count
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages

# Twilio imports
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

import logging

from callManager.views import log_sms, send_message

# Create a logger instance
logger = logging.getLogger('callManager')


@login_required
def admin_dashboard(request):
    if not hasattr(request.user, 'administrator'):
        return redirect('login')
    admindashboard = True
    yesterday = timezone.now().date() - timedelta(days=1)
    search_query = request.GET.get('search', '').strip().lower()
    include_past = request.GET.get('include_past', '') == 'on'
    events = Event.objects.all()
    if not include_past:
        events = events.filter(Q(start_date__gte=yesterday) | Q(end_date__gte=yesterday))
    if search_query:
        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
            'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12}
        terms = search_query.split()
        for term in terms:
            term_filter = Q()
            if term in month_map:
                term_filter = Q(start_date__month=month_map[term])
            elif term.isdigit() and len(term) == 4:
                term_filter = Q(start_date__year=int(term))
            elif re.match(r'\d{4}-\d{2}-\d{2}', term):
                try:
                    search_date = datetime.strptime(term, '%Y-%m-%d').date()
                    term_filter = Q(start_date__exact=search_date) | Q(end_date__exact=search_date)
                except ValueError:
                    pass
            else:
                term_filter = Q(event_name__icontains=term) | Q(location_profile__name__icontains=term)
            events = events.filter(term_filter)
    events = events.order_by('start_date').distinct()
    total_events = events.count()
    pending_requests = LaborRequest.objects.filter(
        availability_response__isnull=True).count()
    declined_requests = LaborRequest.objects.filter(
        availability_response='no').count()
    labor_requirements = LaborRequirement.objects.select_related(
        'labor_type', 'call_time__event').annotate(
        confirmed_count=Count('labor_requests', filter=Q(labor_requests__confirmed=True)))
    unfilled_spots = sum(max(0, lr.needed_labor - lr.confirmed_count) for lr in labor_requirements)
    current_date = timezone.now()
    start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_of_month + timedelta(days=32)).replace(day=1)
    sent_messages = SentSMS.objects.filter(
        datetime_sent__gte=start_of_month,
        datetime_sent__lt=next_month).count()
    event_labor_needs = {}
    for event in events:
        event_requirements = [lr for lr in labor_requirements if lr.call_time.event_id == event.id]
        unfilled_requirements = [
            lr for lr in event_requirements if lr.confirmed_count < lr.needed_labor]
        unfilled_count = len(unfilled_requirements)
        total_unfilled_spots = sum(max(0, lr.needed_labor - lr.confirmed_count) for lr in unfilled_requirements)
        if unfilled_count > 3:
            labor_needs_text = f"{unfilled_count} unfilled, {total_unfilled_spots} total labor needed"
        elif unfilled_count > 0:
            labor_needs_text = ", ".join(
                f"{lr.labor_type.name}: {max(0, lr.needed_labor - lr.confirmed_count)} needed"
                for lr in unfilled_requirements)
        else:
            labor_needs_text = "All calls filled"
        event_labor_needs[event.id] = {
            'unfilled_count': unfilled_count,
            'total_unfilled_spots': total_unfilled_spots,
            'labor_needs_text': labor_needs_text}
    if request.method == "POST":
        phone = request.POST.get('phone')
        if phone and phone != '':
            phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if len(phone) == 10:
                phone = f"+1{phone}"
            elif len(phone) == 11 and phone.startswith('1'):
                phone = f"+{phone}"
            elif len(phone) < 10:
                phone = None
        else:
            phone = None
        if phone:
            invitation = OwnerInvitation.objects.create(phone=phone)
            registration_url = request.build_absolute_uri(reverse('register_owner', args=[str(invitation.token)]))
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN) if settings.TWILIO_ENABLED == 'enabled' else None
            message_body = f'You are invited to join Callman. Use the following link to register:\n{registration_url}'
            if settings.TWILIO_ENABLED == 'enabled' and client:
                try:
                    client.messages.create(
                        body=message_body,
                        from_=settings.TWILIO_PHONE_NUMBER,
                        to=phone)
                    log_sms(request.user.manager.company)
                    messages.success(request, f"Invitation sent to {phone}.")
                except TwilioRestException as e:
                    messages.error(request, f"Failed to send invitation: {str(e)}")
            else:
                log_sms(request.user.manager.company)
                print(message_body)
                messages.success(request, f"Invitation sent for {phone}.")
        else:
            messages.error(request, "Please provide a valid phone number.") 
    context = {
        'events': events,
        'total_events': total_events,
        'pending_requests': pending_requests,
        'sent_messages': sent_messages,
        'declined': declined_requests,
        'unfilled_spots': unfilled_spots,
        'event_labor_needs': event_labor_needs,
        'search_query': search_query,
        'include_past': include_past,
        'admindashboard': admindashboard,
        }
    return render(request, 'callManager/admin_dashboard.html', context)

