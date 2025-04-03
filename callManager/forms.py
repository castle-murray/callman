from django.contrib.auth.models import User
from django import forms
from .models import Event, CallTime, LaborRequirement, LaborType, Worker

class LaborTypeForm(forms.ModelForm):
    class Meta:
        model = LaborType
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
        }

class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['event_name', 'start_date', 'end_date', 'is_single_day', 'event_location', 'event_description']
        widgets = {
            'event_name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'is_single_day': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded dark:bg-gray-800 dark:border-gray-600 dark:text-blue-400'}),
            'event_location': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'event_description': forms.Textarea(attrs={'rows': 4, 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
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
        fields = ['name', 'date', 'time', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'time': forms.TimeInput(attrs={'type': 'time', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'message': forms.Textarea(attrs={'rows': 4, 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
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
        if event and date:
            if date < event.start_date:
                raise forms.ValidationError("Call time date cannot be before the event's start date.")
            if event.end_date and date > event.end_date:
                raise forms.ValidationError("Call time date cannot be after the event's end date.")
        return cleaned_data

class LaborRequirementForm(forms.ModelForm):
    class Meta:
        model = LaborRequirement
        fields = ['labor_type', 'needed_labor']
        widgets = {
            'labor_type': forms.Select(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'needed_labor': forms.NumberInput(attrs={'min': 1, 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_type'].queryset = LaborType.objects.filter(company=company)

class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'phone_number', 'labor_types', 'sms_consent']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'phone_number': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'labor_types': forms.CheckboxSelectMultiple(attrs={'class': 'text-blue-600 dark:text-blue-400'}),
            'sms_consent': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded dark:bg-gray-800 dark:border-gray-600 dark:text-blue-400'}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_types'].queryset = LaborType.objects.filter(company=company)

class WorkerImportForm(forms.Form):
    file = forms.FileField(label="Upload a CSV file with contacts", widget=forms.FileInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}))

class WorkerRegistrationForm(forms.ModelForm):
    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}), required=True)
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}))

    class Meta:
        model = Worker
        fields = ['name', 'phone_number', 'labor_types']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'phone_number': forms.TextInput(attrs={'readonly': 'readonly', 'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
            'labor_types': forms.CheckboxSelectMultiple(attrs={'class': 'text-blue-600 dark:text-blue-400'}),
        }

    def save(self, commit=True):
        worker = super().save(commit=False)
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password']
        )
        worker.user = user
        if commit:
            worker.save()
            self.save_m2m()  # Save labor_types
        return worker

class SkillForm(forms.ModelForm):
    class Meta:
        model = LaborType
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'}),
        }
