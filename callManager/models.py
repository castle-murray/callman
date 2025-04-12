from django.db import models
from django.contrib.auth.models import User
from phonenumber_field.modelfields import PhoneNumberField
import uuid
import random
import pytz

def generate_unique_slug(model_class, length=7):
    while True:
        slug = ''.join([str(random.randint(0, 9)) for _ in range(length)])
        if not model_class.objects.filter(slug=slug).exists():
            return slug

# Company model (e.g., "ABC Production Co.")
class Company(models.Model):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=200)
    state = models.CharField(max_length=200)
    phone_number = PhoneNumberField()
    email = models.EmailField()
    website = models.URLField(max_length=200)

    def __str__(self):
        return self.name

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
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='events')
    created_by = models.ForeignKey('Manager', on_delete=models.SET_NULL, null=True, blank=True)
    slug = models.CharField(max_length=7, unique=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(Event)
        super().save(*args, **kwargs)


    def __str__(self):
        return self.event_name

class CallTime(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='call_times')
    date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=200)  # e.g., "Walk and Chalk", "Pre Rig"
    time = models.TimeField()  # e.g., 08:00, 09:00
    slug = models.CharField(max_length=7, unique=True, blank=True, null=True)
    # New fields for tracking changes
    original_date = models.DateField(null=True, blank=True)
    original_time = models.TimeField(null=True, blank=True)
    last_modified = models.DateTimeField(auto_now=True)
    message = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
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

# Specific labor requirements for an event
class LaborRequirement(models.Model):
    call_time = models.ForeignKey(CallTime, on_delete=models.CASCADE, related_name='labor_requirements', null=True, blank=True)
    labor_type = models.ForeignKey(LaborType, on_delete=models.CASCADE)
    needed_labor = models.IntegerField()
    slug = models.CharField(max_length=7, unique=True, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(LaborRequirement)
        super().save(*args, **kwargs)


    def __str__(self):
        return f"{self.labor_type.name} ({self.needed_labor}) for {self.call_time}"

    class Meta:
        unique_together = ('call_time', 'labor_type')


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

    def __str__(self):
        return self.name or "Unnamed Worker"


class LaborRequest(models.Model):
    RESPONSE_CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
        ('ncns', 'No Call No Show'),
    ]
    worker = models.ForeignKey('Worker', on_delete=models.CASCADE)
    labor_requirement = models.ForeignKey('LaborRequirement', on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    response = models.CharField(max_length=20, choices=RESPONSE_CHOICES, null=True, blank=True)  # Pending is null
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    requested = models.BooleanField(default=False)
    sms_sent = models.BooleanField(default=False)
    event_token = models.CharField(max_length=36, null=True, blank=True)

    def __str__(self):
        worker_name = self.worker.name if self.worker.name else "Unnamed Worker"
        return f"Request: {worker_name} - {self.labor_requirement.labor_type.name}"
    

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
    def hours_worked(self):
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            total_hours = delta.total_seconds() / 3600
            # Deduct 1 hour for each unpaid meal break
            unpaid_breaks = self.meal_breaks.filter(break_type='unpaid').count()
            total_hours -= unpaid_breaks  # 1 hour per unpaid break
            return max(0, total_hours)
        return 0

class MealBreak(models.Model):
    BREAK_TYPES = [
        ('paid', 'Paid'),
        ('unpaid', 'Unpaid 1-Hour Walk-Away'),
    ]
    time_entry = models.ForeignKey('TimeEntry', on_delete=models.CASCADE, related_name='meal_breaks')
    break_time = models.DateTimeField()
    break_type = models.CharField(max_length=10, choices=BREAK_TYPES, default='paid')
    duration = models.DurationField(null=True, blank=True)

    def __str__(self):
        return f"{self.break_type.capitalize()} Break for {self.time_entry.worker.name} at {self.break_time}"
