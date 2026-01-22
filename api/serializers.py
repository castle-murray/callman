from django.contrib.auth.models import User
from callManager.models import (
        Company,
        Event,
        LaborRequest,
        LaborRequirement,
        LaborType,
        LocationProfile,
        ManagerInvitation,
        Worker,
        CallTime,
<<<<<<< Updated upstream
=======
        UserProfile,
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
class WorkerSerializer(serializers.ModelSerializer):
    conflicts = serializers.SerializerMethodField()
    requested = serializers.SerializerMethodField()
    
    def get_conflicts(self, obj):
        return getattr(obj, 'conflicts', [])
    
=======
class LaborTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborType
        fields = '__all__'

    def create(self, validated_data):
        labor_type = LaborType.objects.create(**validated_data)
        return labor_type

class WorkerSerializer(serializers.ModelSerializer):
    conflicts = serializers.SerializerMethodField()
    requested = serializers.SerializerMethodField()
    labor_types = LaborTypeSerializer(many=True, read_only=True)

    def get_conflicts(self, obj):
        return getattr(obj, 'conflicts', [])

>>>>>>> Stashed changes
    def get_requested(self, obj):
        return getattr(obj, 'requested', False)

    class Meta:
        model = Worker
        fields = '__all__'

        def create(self, validated_data):
            worker = Worker.objects.create(**validated_data)
            return worker

class LaborRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborRequest
        fields = '__all__'
        depth = 2

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
<<<<<<< Updated upstream
=======
    call_unixtime = serializers.ReadOnlyField()
>>>>>>> Stashed changes
    class Meta:
        model = CallTime
        fields = '__all__'


    def create(self, validated_data):
        call_time = CallTime.objects.create(**validated_data)
        return call_time


<<<<<<< Updated upstream
class LaborTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LaborType

        fields = '__all__'

    def create(self, validated_data):
        labor_type = LaborType.objects.create(**validated_data)
        return labor_type

=======
>>>>>>> Stashed changes
class ManagerInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManagerInvitation
        fields = '__all__'
<<<<<<< Updated upstream
=======

class UserSerializer(serializers.ModelSerializer):
    phone_number = serializers.CharField(source='profile.phone_number', read_only=True)
    class Meta:
        model = User
        fields = '__all__'
>>>>>>> Stashed changes
