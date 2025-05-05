import string
from django.db import models
from django.contrib.auth.models import User
from phonenumber_field.modelfields import PhoneNumberField
import uuid
import random
import pytz
from datetime import datetime, timedelta

def generate_unique_slug(model_class, length=7):
    while True:
        slug = ''.join([str(random.randint(0, 9)) for _ in range(length)])
        if not model_class.objects.filter(slug=slug).exists():
            return slug

class Administrator(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='administrator')
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Administrator)"

# Company model (e.g., "ABC Production Co.")
class Company(models.Model):
    name = models.CharField(max_length=200)
    meal_penalty_trigger_time = models.PositiveIntegerField(default=5, help_text="Hours after start time to trigger meal penalty")
    hour_round_up = models.PositiveIntegerField(default=15, help_text="Minutes to round up hours worked")
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=200)
    state = models.CharField(max_length=200)
    phone_number = PhoneNumberField()
    email = models.EmailField()
    website = models.URLField(max_length=200)
    time_tracking = models.BooleanField(default=False, help_text="Enable time tracking for this company")
    minimum_hours = models.PositiveIntegerField(default=4, help_text="Minimum hours for a call time")


    def __str__(self):
        return self.name

class Owner(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='owner')
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='owners')
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Owner)"

class OwnerInvitation(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    phone = models.CharField(max_length=15, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    def __str__(self):
        return f"Owner Invitation for {self.company_name} ({self.token})"


class ManagerInvitation(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='invitations')
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    def __str__(self):
        return f"Invitation for {self.company.name} ({self.token})"

class Steward(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='steward')
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='stewards')
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} (Steward)"

class StewardInvitation(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    worker = models.ForeignKey('Worker', on_delete=models.CASCADE, related_name='steward_invitations')
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='steward_invitations')
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    def __str__(self):
        return f"Steward Invitation for {self.company.name} ({self.token})"

class SentSMS(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='sent_sms')
    datetime_sent = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SMS Messages - {self.company.name} on {self.datetime_sent}"

# Manager profile (tied to a company)
class Manager(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='managers')
    per_page_preference = models.PositiveIntegerField(default=10, choices=[(10, '10'), (25, '25'), (50, '50'), (100, '100')])
    timezone = models.CharField(max_length=100, default='America/New_York', choices=[(tz, tz) for tz in pytz.common_timezones])

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.company.name})"

# Reusable labor type defined by the company
class LaborType(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='labor_types')
    name = models.CharField(max_length=200)  # e.g., "Stagehand", "Lighting Tech"

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ('company', 'name')  # Prevent duplicate labor types per company

# Event model for concerts or entertainment gigs
class Event(models.Model):
    event_name = models.CharField(max_length=200)
    event_location = models.CharField(max_length=200)
    start_date = models.DateField(null=True, blank=True )  # New start date
    end_date = models.DateField(null=True, blank=True )    # New end date
    is_single_day = models.BooleanField(default=False)  # New single-day flag
    event_description = models.TextField()
    location_profile = models.ForeignKey('LocationProfile', on_delete=models.SET_NULL, null=True, blank=True)
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='events')
    created_by = models.ForeignKey('Manager', on_delete=models.SET_NULL, null=True, blank=True)
    slug = models.CharField(max_length=7, unique=True, blank=True, null=True)
    steward = models.ForeignKey('Steward', on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(Event)
        super().save(*args, **kwargs)


    def __str__(self):
        return self.event_name


class CallTime(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='call_times')
    date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=200)
    time = models.TimeField()
    minimum_hours = models.PositiveIntegerField(blank=True, null=True, help_text="Minimum hours for this call time (defaults to event's location profile or company)")
    slug = models.CharField(max_length=7, unique=True, blank=True, null=True)
    original_date = models.DateField(null=True, blank=True)
    original_time = models.TimeField(null=True, blank=True)
    last_modified = models.DateTimeField(auto_now=True)
    message = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk and self.minimum_hours is None:
            # Set default minimum_hours from event's location profile or company
            if self.event.location_profile and self.event.location_profile.minimum_hours is not None:
                self.minimum_hours = self.event.location_profile.minimum_hours
            else:
                self.minimum_hours = self.event.company.minimum_hours
        if not self.pk:  # New instance
            self.original_date = self.date
            self.original_time = self.time
        elif self.has_changed():  # Existing instance with changes
            if not self.original_date:
                self.original_date = CallTime.objects.get(pk=self.pk).date
            if not self.original_time:
                self.original_time = CallTime.objects.get(pk=self.pk).time
        super().save(*args, **kwargs)
        if not self.slug:
            self.slug = generate_unique_slug(CallTime)
            super().save(update_fields=['slug'])

    def has_changed(self):
        if not self.pk:
            return False
        original = CallTime.objects.get(pk=self.pk)
        return self.date != original.date or self.time != original.time

    def __str__(self):
        return f"{self.name} at {self.time} ({self.event})"


class LaborRequirement(models.Model):
    call_time = models.ForeignKey(CallTime, on_delete=models.CASCADE, related_name='labor_requirements', null=True, blank=True)
    labor_type = models.ForeignKey(LaborType, on_delete=models.CASCADE)
    needed_labor = models.IntegerField()
    minimum_hours = models.PositiveIntegerField(blank=True, null=True, help_text="Minimum hours for this labor requirement (defaults to call time)")
    slug = models.CharField(max_length=7, unique=True, blank=True, null=True)
    fcfs_positions = models.PositiveIntegerField(default=0, help_text="Number of positions filled by First Come First Served")

    def save(self, *args, **kwargs):
        if not self.pk and self.minimum_hours is None and self.call_time:
            self.minimum_hours = self.call_time.minimum_hours
        if not self.slug:
            self.slug = generate_unique_slug(LaborRequirement)
        if self.fcfs_positions > self.needed_labor:
            self.fcfs_positions = self.needed_labor
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.labor_type.name} ({self.needed_labor}) for {self.call_time}"

    class Meta:
        unique_together = ('call_time', 'labor_type')


class LaborRequest(models.Model):
    RESPONSE_CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
        ('ncns', 'No Call No Show'),
    ]
    worker = models.ForeignKey('Worker', on_delete=models.CASCADE)
    labor_requirement = models.ForeignKey('LaborRequirement', on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    availability_response = models.CharField(max_length=20, choices=RESPONSE_CHOICES, null=True, blank=True)
    confirmed = models.BooleanField(default=False)
    is_reserved = models.BooleanField(default=False, help_text="Reserve this position for the worker")
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    requested = models.BooleanField(default=False)
    sms_sent = models.BooleanField(default=False)
    event_token = models.CharField(max_length=36, null=True, blank=True)

    def __str__(self):
        worker_name = self.worker.name if self.worker.name else "Unnamed Worker"
        return f"Request: {worker_name} - {self.labor_requirement.labor_type.name}"
    

class Worker(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    phone_number = models.CharField(max_length=15)  # No unique constraint
    name = models.CharField(max_length=200, blank=True)
    companies = models.ManyToManyField('Company', related_name='workers', blank=True)  # Managers will populate this
    labor_types = models.ManyToManyField('LaborType', blank=True)
    sms_consent = models.BooleanField(default=False)
    sent_consent_msg = models.BooleanField(default=False)
    stop_sms = models.BooleanField(default=False)
    nocallnoshow = models.IntegerField(default=0)  # No-call, no-show counter
    slug = models.CharField(max_length=10, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.slug:
            while True:
                slug = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
                if not Worker.objects.filter(slug=slug).exists():
                    self.slug = slug
                    break
        super().save(*args, **kwargs)

    def add_company(self, company):
        if not self.companies.filter(id=company.id).exists():
            self.companies.add(company)
            self.save()

    def formatted_phone_number(self):
        phone = self.phone_number.replace('-', '').replace('(', '').replace(')', '').replace(' ', '')
        if phone.startswith('+1'):
            phone = phone[2:]  # Remove +1 prefix
        if len(phone) == 10 and phone.isdigit():
            return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
        return self.phone_number

    def __str__(self):
        return self.name or "Unnamed Worker"


class ClockInToken(models.Model):
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='clock_in_tokens')
    worker = models.ForeignKey('Worker', on_delete=models.CASCADE, related_name='clock_in_tokens',null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    qr_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Token for {self.worker.name} at {self.event.event_name} ({self.token})"

    class Meta:
        unique_together = ('event', 'worker')

class TimeEntry(models.Model):
    labor_request = models.ForeignKey('LaborRequest', on_delete=models.CASCADE, related_name='time_entries')
    worker = models.ForeignKey('Worker', on_delete=models.CASCADE)
    call_time = models.ForeignKey('CallTime', on_delete=models.CASCADE)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('labor_request', 'worker', 'call_time')

    def __str__(self):
        return f"{self.worker.name} - {self.call_time.name} ({self.start_time} to {self.end_time})"

    @property
    def normal_hours(self):
        if not (self.start_time and self.end_time):
            return 0
        normal_hours = 0
        current_time = self.start_time
        trigger_duration = self.labor_request.labor_requirement.call_time.event.company.meal_penalty_trigger_time
        breaks = list(self.meal_breaks.order_by('break_time'))
        unpaid_breaks = self.meal_breaks.filter(break_type='unpaid').count()

        for i, meal_break in enumerate(breaks):
            break_start = meal_break.break_time
            break_end = break_start + timedelta(minutes=30) if meal_break.break_type == 'paid' else break_start + timedelta(hours=1)
            trigger_time = current_time + timedelta(hours=trigger_duration)

            if break_start > trigger_time:
                normal_hours += (trigger_time - current_time).total_seconds() / 3600
                current_time = trigger_time
            else:
                normal_hours += (break_start - current_time).total_seconds() / 3600
                current_time = break_start

            if meal_break.break_type == 'paid':
                paid_duration = (break_end - break_start).total_seconds() / 3600
                normal_hours += paid_duration

            current_time = break_end
            if current_time >= self.end_time:
                break

        if current_time < self.end_time:
            trigger_time = current_time + timedelta(hours=trigger_duration)
            end_normal = min(trigger_time, self.end_time)
            normal_hours += (end_normal - current_time).total_seconds() / 3600

        normal_hours -= unpaid_breaks
        return max(0, normal_hours)

    @property
    def meal_penalty_hours(self):
        if not (self.start_time and self.end_time):
            return 0
        penalty_hours = 0
        current_time = self.start_time
        trigger_duration = self.labor_request.labor_requirement.call_time.event.company.meal_penalty_trigger_time
        breaks = list(self.meal_breaks.order_by('break_time'))

        for i, meal_break in enumerate(breaks):
            break_start = meal_break.break_time
            break_end = break_start + timedelta(minutes=30) if meal_break.break_type == 'paid' else break_start + timedelta(hours=1)
            trigger_time = current_time + timedelta(hours=trigger_duration)

            if trigger_time < break_start:
                penalty_end = min(break_start, self.end_time)
                if penalty_end > trigger_time:
                    penalty_hours += (penalty_end - trigger_time).total_seconds() / 3600
            current_time = break_end

            if current_time >= self.end_time:
                break

        if current_time < self.end_time:
            trigger_time = current_time + timedelta(hours=trigger_duration)
            if self.end_time > trigger_time:
                penalty_hours += (self.end_time - trigger_time).total_seconds() / 3600

        return max(0, penalty_hours)

    @property
    def total_hours_worked(self):
        if not (self.start_time and self.end_time):
            return 0
        delta = self.end_time - self.start_time
        total_hours = delta.total_seconds() / 3600
        unpaid_breaks = self.meal_breaks.filter(break_type='unpaid').count()
        total_hours -= unpaid_breaks
        return max(0, total_hours)

class MealBreak(models.Model):
    BREAK_TYPES = [
        ('paid', 'Paid 30min'),
        ('unpaid', 'Unpaid 1hr'),
    ]
    time_entry = models.ForeignKey('TimeEntry', on_delete=models.CASCADE, related_name='meal_breaks')
    break_time = models.DateTimeField()
    break_type = models.CharField(max_length=10, choices=BREAK_TYPES, default='paid')
    duration = models.DurationField(null=True, blank=True)

    def __str__(self):
        return f"{self.break_type.capitalize()} Break for {self.time_entry.worker.name} at {self.break_time}"

class TemporaryScanner(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='temporary_scanners')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    def __str__(self):
        return f"Temporary Scanner for {self.event.event_name} ({self.token})"


class LocationProfile(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='location_profiles')
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=200)
    minimum_hours = models.PositiveIntegerField(blank=True, null=True, help_text="Minimum hours for a call time (defaults to company value if blank)")
    meal_penalty_trigger_time = models.PositiveIntegerField(blank=True, null=True, help_text="Hours after start time to trigger meal penalty (defaults to company value if blank)")
    hour_round_up = models.PositiveIntegerField(blank=True, null=True, help_text="Minutes to round up hours worked (defaults to company value if blank)")
    def __str__(self):
        return f"{self.name} ({self.company.name})"
    def save(self, *args, **kwargs):
        if self.minimum_hours is None:
            self.minimum_hours = self.company.minimum_hours
        if self.meal_penalty_trigger_time is None:
            self.meal_penalty_trigger_time = self.company.meal_penalty_trigger_time
        if self.hour_round_up is None:
            self.hour_round_up = self.company.hour_round_up
        super().save(*args, **kwargs)
