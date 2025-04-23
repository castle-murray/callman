from django.contrib import admin
from .models import Event, CallTime, LaborRequirement, LaborType, SentSMS, Worker, Manager, LaborRequest, TimeEntry, MealBreak, Company

    
    
@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'email', 'meal_penalty_trigger_time', 'hour_round_up')
    list_filter = ('state', 'city')
    search_fields = ('name', 'email', 'phone_number')
    fieldsets = (
        (None, {
            'fields': ('name', 'address', 'city', 'state', 'phone_number', 'email', 'website')
        }),
        ('Time Settings', {
            'fields': ('meal_penalty_trigger_time', 'hour_round_up')
        }),
    )

# Inline for MealBreak in TimeEntryAdmin
class MealBreakInline(admin.TabularInline):
    model = MealBreak
    extra = 0
    fields = ('break_time', 'break_type', 'duration')
    readonly_fields = ('duration',)
    ordering = ('break_time',)

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('event_name', 'start_date', 'end_date', 'is_single_day', 'event_location')
    list_filter = ('is_single_day', 'start_date')
    search_fields = ('event_name', 'event_location')

@admin.register(CallTime)
class CallTimeAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'date', 'time')
    list_filter = ('event', 'date')
    search_fields = ('name',)

@admin.register(LaborRequirement)
class LaborRequirementAdmin(admin.ModelAdmin):
    list_display = ('labor_type', 'call_time', 'needed_labor', 'fcfs_positions')
    list_filter = ('labor_type', 'call_time')
    search_fields = ('labor_type__name',)


@admin.register(LaborType)
class LaborTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'company')
    list_filter = ('company',)
    search_fields = ('name',)

@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'nocallnoshow')
    list_filter = ('companies',)
    search_fields = ('name', 'phone_number')

@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'timezone')
    list_filter = ('company',)
    search_fields = ('user__username',)

@admin.register(LaborRequest)
class LaborRequestAdmin(admin.ModelAdmin):
    list_display = ('worker', 'labor_requirement', 'availability_response', 'confirmed', 'is_reserved', 'requested')
    list_filter = ('availability_response', 'confirmed', 'is_reserved', 'requested')
    search_fields = ('worker__name', 'labor_requirement__labor_type__name')
    actions = ['confirm_workers']

    def confirm_workers(self, request, queryset):
        for labor_request in queryset.filter(availability_response='yes', confirmed=False):
            confirmed_count = LaborRequest.objects.filter(
                labor_requirement=labor_request.labor_requirement,
                confirmed=True
            ).count()
            if confirmed_count < labor_request.labor_requirement.needed_labor:
                labor_request.confirmed = True
                labor_request.save()
        self.message_user(request, "Selected workers confirmed where labor requirements allowed.")
    confirm_workers.short_description = "Confirm selected workers for call times"

@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ('worker', 'call_time', 'start_time', 'end_time', 'normal_hours', 'meal_penalty_hours', 'total_hours_worked')
    list_filter = ('call_time',)
    search_fields = ('worker__name',)
    readonly_fields = ('normal_hours', 'meal_penalty_hours', 'total_hours_worked', 'created_at', 'updated_at')
    inlines = [MealBreakInline]
    ordering = ('-start_time',)

    def normal_hours(self, obj):
        return f"{obj.normal_hours:.2f}" if obj.normal_hours else "-"
    normal_hours.short_description = "Normal Hours"

    def meal_penalty_hours(self, obj):
        return f"{obj.meal_penalty_hours:.2f}" if obj.meal_penalty_hours else "-"
    meal_penalty_hours.short_description = "Meal Penalty Hours"

    def total_hours_worked(self, obj):
        return f"{obj.total_hours_worked:.2f}" if obj.total_hours_worked else "-"
    total_hours_worked.short_description = "Total Hours Worked"

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

@admin.register(SentSMS)
class SentSMSAdmin(admin.ModelAdmin):
    list_display = ('company', 'datetime_sent')
    list_filter = ('datetime_sent',)
    ordering = ('datetime_sent',)
