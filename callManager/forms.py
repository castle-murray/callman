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
        fields = ['event_name', 'start_date', 'end_date', 'is_single_day', 'event_location', 'event_description']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'event_description': forms.Textarea(attrs={'rows': 4}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        is_single_day = cleaned_data.get('is_single_day')

        if is_single_day and start_date and end_date and start_date != end_date:
            raise forms.ValidationError("Single-day events must have the same start and end date.")
        elif start_date and end_date and start_date > end_date:
            raise forms.ValidationError("End date must be on or after start date.")
        return cleaned_data

class CallTimeForm(forms.ModelForm):
    class Meta:
        model = CallTime
        fields = ['name', 'date', 'time']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'time': forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        event = kwargs.pop('event', None)
        super().__init__(*args, **kwargs)
        if event and event.is_single_day:
            self.fields['date'].initial = event.start_date
            self.fields['date'].disabled = True
            self.fields['date'].widget.attrs['readonly'] = True

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get('date')
        event = self.instance.event if self.instance and hasattr(self.instance, 'event') else None
        if event:
            if date < event.start_date or date > event.end_date:
                raise forms.ValidationError("Call time date must be within the event's date range.")
        return cleaned_data

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

class WorkerRegistrationForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'phone_number', 'labor_types']
        widgets = {
            'phone_number': forms.TextInput(attrs={'readonly': 'readonly'}),
            'labor_types': forms.CheckboxSelectMultiple,
        }
