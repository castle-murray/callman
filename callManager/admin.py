# callManager/admin.py
from django.contrib import admin
from .models import Company, Manager, Event, CallTime, LaborType, LaborRequirement, Worker, LaborRequest, TimeEntry, MealBreak

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'phone_number', 'email')
    search_fields = ('name', 'email')
    list_filter = ('state',)

@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'user_email')
    search_fields = ('user__username', 'user__email', 'company__name')
    list_filter = ('company',)
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('event_name', 'company', 'created_by')
    search_fields = ('event_name', 'event_location', 'company__name')
    list_filter = ('company',) 

@admin.register(CallTime)
class CallTimeAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'time', 'event')
    search_fields = ('name', 'event__event_name')
    list_filter = ('event__company', 'time', 'date')
    date_hierarchy = 'date'

@admin.register(LaborType)
class LaborTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'company')
    search_fields = ('name', 'company__name')
    list_filter = ('company',)

@admin.register(LaborRequirement)
class LaborRequirementAdmin(admin.ModelAdmin):
    list_display = ('labor_type', 'call_time', 'needed_labor')
    search_fields = ('labor_type__name', 'call_time__name', 'call_time__event__event_name')
    list_filter = ('call_time__event__company', 'labor_type')

@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number')
    search_fields = ('name', 'phone_number')
    list_filter = ('labor_types',)

@admin.register(LaborRequest)
class LaborRequestAdmin(admin.ModelAdmin):
    list_display = ('worker', 'labor_requirement', 'response', 'requested_at', 'responded_at')
    search_fields = ('worker__name', 'labor_requirement__labor_type__name', 'labor_requirement__call_time__name')
    list_filter = ('response', 'labor_requirement__call_time__event__company')
    date_hierarchy = 'requested_at'

@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ('worker', 'call_time', 'start_time', 'end_time', 'hours_worked')
    list_filter = ('call_time',)
    search_fields = ('worker__name',)
    readonly_fields = ('hours_worked', 'created_at', 'updated_at')
    ordering = ('-start_time',)

    def hours_worked(self, obj):
        return f"{obj.hours_worked:.2f}" if obj.hours_worked else "-"
    hours_worked.short_description = "Hours Worked"

@admin.register(MealBreak)
class MealBreakAdmin(admin.ModelAdmin):
    list_display = ('worker_name', 'call_time_name', 'break_time', 'break_type', 'duration')
    list_filter = ('break_type', 'time_entry__call_time')
    search_fields = ('time_entry__worker__name', 'time_entry__call_time__name')
    readonly_fields = ('duration',)
    ordering = ('-break_time',)

    def worker_name(self, obj):
        return obj.time_entry.worker.name or "Unnamed Worker"
    worker_name.short_description = "Worker"

    def call_time_name(self, obj):
        return obj.time_entry.call_time.name
    call_time_name.short_description = "Call Time"

    def duration(self, obj):
        return obj.duration if obj.duration else "-"
    duration.short_description = "Duration"
