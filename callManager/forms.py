from django.contrib.auth.models import User
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Event, CallTime, LaborRequirement, LaborType, Worker, Company

class LaborTypeForm(forms.ModelForm):
    class Meta:
        model = LaborType
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError("Labor type name cannot be empty.")
        return name

class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['event_name', 'start_date', 'end_date', 'is_single_day', 'event_location', 'event_description']
        widgets = {
            'event_name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'is_single_day': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-text-blue border-light rounded dark:bg-dark-card-bg dark:border-dark-border dark:text-dark-text-blue'}),
            'event_location': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'event_description': forms.Textarea(attrs={'rows': 4, 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
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
            'name': forms.TextInput(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'time': forms.TimeInput(attrs={'type': 'time', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'message': forms.Textarea(attrs={'rows': 4, 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
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
            'labor_type': forms.Select(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'needed_labor': forms.NumberInput(attrs={'min': 1, 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_type'].queryset = LaborType.objects.filter(company=company)

class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'phone_number', 'labor_types', 'sms_consent', 'nocallnoshow']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'phone_number': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'labor_types': forms.CheckboxSelectMultiple(attrs={'class': 'text-text-blue dark:text-dark-text-blue'}),
            'sms_consent': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-text-blue border-light rounded dark:bg-dark-card-bg dark:border-dark-border dark:text-dark-text-blue'}),
            'nocallnoshow': forms.NumberInput(attrs={'readonly': 'readonly', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_types'].queryset = LaborType.objects.filter(company=company)
        self.fields['nocallnoshow'].required = False

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        if phone_number and len(phone_number) > 15:
            raise forms.ValidationError("Phone number must be 15 characters or less.")
        return phone_number


class WorkerImportForm(forms.Form):
    file = forms.FileField(label="Upload a CSV file with contacts", widget=forms.FileInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))

class WorkerRegistrationForm(forms.ModelForm):
    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}), required=True)
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))

    class Meta:
        model = Worker
        fields = ['name', 'phone_number', 'labor_types']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'phone_number': forms.TextInput(attrs={'readonly': 'readonly', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'labor_types': forms.CheckboxSelectMultiple(attrs={'class': 'text-text-blue dark:text-dark-text-blue'}),
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
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border autofocus'}),
        }


class OwnerRegistrationForm(UserCreationForm):
    company_name = forms.CharField(max_length=200, required=True)
    class Meta:
        model = User
        fields = ['username', 'password1', 'password2', 'company_name']

class CompanyForm(forms.ModelForm):
    name = forms.CharField(
        label="Company Name",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    meal_penalty_trigger_time = forms.IntegerField(
        label="Meal Penalty Trigger Time (Hours)",
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    hour_round_up = forms.IntegerField(
        label="Minutes to round to next half hour",
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    address = forms.CharField(
        label="Address",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    city = forms.CharField(
        label="City",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    state = forms.CharField(
        label="State",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    phone_number = forms.CharField(
        label="Phone Number",
        widget=forms.TextInput(attrs={'type': 'tel', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    website = forms.URLField(
        label="Website",
        widget=forms.URLInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    time_tracking = forms.BooleanField(
        label="Enable Time Tracking",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-text-blue dark:text-dark-text-blue'}))
    minimum_hours = forms.IntegerField(
        label="Minimum Call Time Hours",
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))

    class Meta:
        model = Company
        fields = [
            'name', 'meal_penalty_trigger_time', 'hour_round_up', 'address',
            'city', 'state', 'phone_number', 'email', 'website',
            'time_tracking', 'minimum_hours']
