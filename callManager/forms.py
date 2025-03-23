# callManager/forms.py
from django import forms
from .models import Event, CallTime, LaborRequirement, LaborType, Worker

class LaborTypeForm(forms.ModelForm):
    class Meta:
        model = LaborType
        fields = ['name']


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['event_name', 'event_date', 'event_location', 'event_description']
        widgets = {
            'event_date': forms.DateInput(attrs={'type': 'date'}),
            'event_description': forms.Textarea(attrs={'rows': 4}),
        }

class CallTimeForm(forms.ModelForm):
    class Meta:
        model = CallTime
        fields = ['name', 'time']
        widgets = {
            'time': forms.TimeInput(attrs={'type': 'time'}),
        }

class LaborRequirementForm(forms.ModelForm):
    class Meta:
        model = LaborRequirement
        fields = ['labor_type', 'needed_labor']
        widgets = {
            'needed_labor': forms.NumberInput(attrs={'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_type'].queryset = LaborType.objects.filter(company=company)

class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'phone_number', 'labor_types']
        widgets = {
            'labor_types': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_types'].queryset = LaborType.objects.filter(company=company)

class WorkerImportForm(forms.Form):
    file = forms.FileField(label="Upload a CSV file with contacts")
