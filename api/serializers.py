from django.contrib.auth.models import User
from callManager.models import (
        AltPhone,
        Company,
        Event,
        LaborRequest,
        LaborRequirement,
        LaborType,
        LocationProfile,
        ManagerInvitation,
        Worker,
        CallTime,
        UserProfile,
        TimeEntry,
        MealBreak,
        ScheduledReminder,
        )
from rest_framework import serializers

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}


    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user

class EventSerializer(serializers.ModelSerializer):
    filled = serializers.BooleanField(read_only=True)
    unfilled_count = serializers.IntegerField(read_only=True)
    class Meta:
        model = Event
        fields = '__all__'
        depth = 3 # Include related fields
        

    def create(self, validated_data):
        event = Event.objects.create(**validated_data)
        return event

class LaborTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborType
        fields = '__all__'

    def create(self, validated_data):
        labor_type = LaborType.objects.create(**validated_data)
        return labor_type

class AltPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = AltPhone
        fields = ['id', 'phone_number', 'label']

class WorkerSerializer(serializers.ModelSerializer):
    conflicts = serializers.SerializerMethodField()
    requested = serializers.SerializerMethodField()
    reserved = serializers.SerializerMethodField()
    labor_types = LaborTypeSerializer(many=True, read_only=True)
    alt_phones = AltPhoneSerializer(many=True, read_only=True)

    def get_conflicts(self, obj):
        return getattr(obj, 'conflicts', [])

    def get_requested(self, obj):
        return getattr(obj, 'requested', False)

    def get_reserved(self, obj):
        return getattr(obj, 'reserved', False)

    class Meta:
        model = Worker
        fields = '__all__'

        def create(self, validated_data):
            worker = Worker.objects.create(**validated_data)
            return worker

class MealBreakSerializer(serializers.ModelSerializer):
    duration = serializers.SerializerMethodField()

    def get_duration(self, obj):
        return obj.duration.total_seconds() / 60 if obj.duration else 0

    class Meta:
        model = MealBreak
        fields = ['id', 'break_time', 'duration', 'break_type']

class TimeEntrySerializer(serializers.ModelSerializer):
    normal_hours = serializers.SerializerMethodField()
    meal_penalty_hours = serializers.SerializerMethodField()
    total_hours_worked = serializers.SerializerMethodField()
    meal_breaks = MealBreakSerializer(many=True, read_only=True)

    def get_normal_hours(self, obj):
        return obj.normal_hours

    def get_meal_penalty_hours(self, obj):
        return obj.meal_penalty_hours

    def get_total_hours_worked(self, obj):
        return obj.total_hours_worked

    class Meta:
        model = TimeEntry
        fields = [
            'id', 'labor_request', 'worker', 'call_time',
            'start_time', 'end_time', 'created_at', 'updated_at',
            'meal_breaks', 'normal_hours', 'meal_penalty_hours', 'total_hours_worked'
        ]

class LaborRequestTrackingSerializer(serializers.ModelSerializer):
    time_entry = serializers.SerializerMethodField()

    def get_time_entry(self, obj):
        time_entry = obj.time_entries.first()
        if time_entry:
            return TimeEntrySerializer(time_entry).data
        return None

    class Meta:
        model = LaborRequest
        fields = ['id', 'worker', 'labor_requirement', 'time_entry', 'ncns']
        depth = 2

class LaborRequestSerializer(serializers.ModelSerializer):
    message = serializers.SerializerMethodField()
    time_entries = TimeEntrySerializer(read_only=True, many=True)

    def get_message(self, obj):
        confirmation = obj.time_change_confirmations.first()
        return confirmation.message if confirmation else None

    class Meta:
        model = LaborRequest
        fields = '__all__'
        depth = 3

        def create(self, validated_data):
            labor_request = LaborRequest.objects.create(**validated_data)
            return labor_request

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'


class LocationProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationProfile
        fields = '__all__'

        def create(self, validated_data):
            location_profile = LocationProfile.objects.create(**validated_data)
            return location_profile

class LaborRequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborRequirement
        fields = '__all__'
        depth = 1
    

class LaborRequirementCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborRequirement
        fields = '__all__'
    
    def create(self, validated_data):
        labor_requirement = LaborRequirement.objects.create(**validated_data)
        return labor_requirement

class CallTimeSerializer(serializers.ModelSerializer):
    labor_requirements = LaborRequirementSerializer(many=True, read_only=True)
    call_unixtime = serializers.ReadOnlyField()
    event_slug = serializers.CharField(source='event.slug', read_only=True)
    event_name = serializers.CharField(source='event.event_name', read_only=True)
    class Meta:
        model = CallTime
        fields = '__all__'


    def create(self, validated_data):
        call_time = CallTime.objects.create(**validated_data)
        return call_time


class ManagerInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManagerInvitation
        fields = '__all__'

class UserSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(source='profile.phone_number', read_only=True)
    class Meta:
        model = User
        fields = '__all__'

class ScheduledReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledReminder
        fields = '__all__'
