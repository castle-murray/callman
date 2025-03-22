# callManager/admin.py
from django.contrib import admin
from .models import Company, Manager, Event, CallTime, LaborType, LaborRequirement, Worker, LaborRequest

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
    list_display = ('event_name', 'event_date', 'company', 'created_by')
    search_fields = ('event_name', 'event_location', 'company__name')
    list_filter = ('company', 'event_date')
    date_hierarchy = 'event_date'

@admin.register(CallTime)
class CallTimeAdmin(admin.ModelAdmin):
    list_display = ('name', 'time', 'event')
    search_fields = ('name', 'event__event_name')
    list_filter = ('event__company', 'time')

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
