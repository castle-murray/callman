from django.db import models
from django.contrib.auth.models import User
from phonenumber_field.modelfields import PhoneNumberField
import uuid

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

    def __str__(self):
        return self.event_name

class CallTime(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='call_times')
    date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=200)  # e.g., "Walk and Chalk", "Pre Rig"
    time = models.TimeField()  # e.g., 08:00, 09:00

    def __str__(self):
        return f"{self.name} at {self.time} ({self.event})"

# Specific labor requirements for an event
class LaborRequirement(models.Model):
    call_time = models.ForeignKey(CallTime, on_delete=models.CASCADE, related_name='labor_requirements', null=True, blank=True)
    labor_type = models.ForeignKey(LaborType, on_delete=models.CASCADE)
    needed_labor = models.IntegerField()

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
    stop_sms = models.BooleanField(default=False)

    def __str__(self):
        return self.name or "Unnamed Worker"


# Tracks worker assignments and responses
class LaborRequest(models.Model):
    worker = models.ForeignKey('Worker', on_delete=models.CASCADE)
    labor_requirement = models.ForeignKey('LaborRequirement', on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    response = models.CharField(max_length=20, choices=[('yes', 'Yes'), ('no', 'No')], null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    requested = models.BooleanField(default=False)
    sms_sent = models.BooleanField(default=False)
    event_token = models.CharField(max_length=36, null=True, blank=True)  # Add this if missing

    def __str__(self):
        worker_name = self.worker.name if self.worker.name else "Unnamed Worker"
        return f"Request: {worker_name} - {self.labor_requirement.labor_type.name}"
