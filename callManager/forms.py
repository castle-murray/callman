from django.contrib.auth.models import User
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Event, CallTime, LaborRequirement, LaborType, Worker, Company, LocationProfile
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password

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
    event_name = forms.CharField(
        label="Event Name",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    start_date = forms.DateField(
        label="Start Date",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    end_date = forms.DateField(
        label="End Date",
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    is_single_day = forms.BooleanField(
        label="Single Day Event",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-text-blue border-light rounded dark:bg-dark-card-bg dark:border-dark-border dark:text-dark-text-blue'}))
    location_profile = forms.ModelChoiceField(
        label="Location Profile",
        queryset=LocationProfile.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    event_description = forms.CharField(
        label="Event Description",
        required=False,
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields['location_profile'].queryset = company.location_profiles.all()
            self.fields['location_profile'].label_from_instance = lambda obj: obj.name
        else:
            self.fields['location_profile'].queryset = LocationProfile.objects.none()
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
    class Meta:
        model = Event
        fields = ['event_name', 'start_date', 'is_single_day', 'end_date', 'location_profile', 'event_description']


class CallTimeForm(forms.ModelForm):
    name = forms.CharField(
        label="Call Time Name",
        widget=forms.TextInput(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    time = forms.TimeField(
        label="Time",
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    minimum_hours = forms.IntegerField(
        label="Minimum Hours",
        required=False,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    message = forms.CharField(
        label="Message",
        required=False,
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event:
            self.fields['date'].initial = event.start_date if event.is_single_day else None
            self.fields['date'].disabled = event.is_single_day
            self.fields['date'].widget.attrs['readonly'] = event.is_single_day
            # Pre-populate minimum_hours from event's location profile or company
            if event.location_profile and event.location_profile.minimum_hours is not None:
                self.fields['minimum_hours'].initial = event.location_profile.minimum_hours
            else:
                self.fields['minimum_hours'].initial = event.company.minimum_hours

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

    class Meta:
        model = CallTime
        fields = ['name', 'date', 'time', 'minimum_hours', 'message']

class LaborRequirementForm(forms.ModelForm):
    labor_type = forms.ModelChoiceField(
        label="Labor Type",
        queryset=LaborType.objects.none(),
        widget=forms.Select(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    needed_labor = forms.IntegerField(
        label="Needed Labor",
        widget=forms.NumberInput(attrs={'min': 1, 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    minimum_hours = forms.IntegerField(
        label="Minimum Hours",
        required=False,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))

    def __init__(self, *args, company=None, call_time=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_type'].queryset = LaborType.objects.filter(company=company)
        if call_time:
            self.fields['minimum_hours'].initial = call_time.minimum_hours

    class Meta:
        model = LaborRequirement
        fields = ['labor_type', 'needed_labor', 'minimum_hours']

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


class WorkerFormLite(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['name', 'phone_number']
        widgets = {
            'name': forms.TextInput(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
            'phone_number': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if company:
            self.fields['labor_types'].queryset = LaborType.objects.filter(company=company)

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        if phone_number:
            phone_number = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if len(phone_number) == 10:
                phone_number = f"+1{phone_number}"
            elif len(phone_number) == 11 and phone_number.startswith('1'):
                phone_number = f"+{phone_number}"
            elif len(phone_number) < 10:
                raise forms.ValidationError("Please provide a valid phone number.")
            elif len(phone_number) == 11 and not phone_number.startswith('1'):
                raise forms.ValidationError("Please provide a valid phone number.")
            elif len(phone_number) == 12 and not phone_number.startswith('+'):
                raise forms.ValidationError("Please provide a valid phone number.")
            elif len(phone_number) > 15:
                raise forms.ValidationError("Phone number must be 15 characters or less.")
        return phone_number


class WorkerImportForm(forms.Form):
    file = forms.FileField(label="Upload a CSV file with contacts", widget=forms.FileInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))


class WorkerRegistrationForm(UserCreationForm):
    phone_number = forms.CharField(
        label="Phone Number",
        widget=forms.HiddenInput(),
        error_messages={
            'required': 'Phone number is required.',
            'invalid': 'Please provide a valid phone number.'
        }
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'placeholder': 'Email', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        error_messages={
            'required': 'Email address is required.',
            'invalid': 'Please enter a valid email address.'
        }
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2', 'phone_number']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Username', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'password1': forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'password2': forms.PasswordInput(attrs={'placeholder': 'Confirm Password', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        }
        error_messages = {
            'username': {
                'required': 'Username is required.',
                'unique': 'This username is already taken.',
                'invalid': 'Please enter a valid username.'
            },
            'password2': {
                'required': 'Please confirm your password.',
                'password_mismatch': 'Passwords do not match.'
            }
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise ValidationError("This email address is already in use.")
        return email

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        if password1:
            try:
                validate_password(password1, self.instance)
            except ValidationError as e:
                raise ValidationError(e.messages)
        return password1

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        phone_number = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if len(phone_number) == 10:
            phone_number = f"+1{phone_number}"
        elif len(phone_number) == 11 and phone_number.startswith('1'):
            phone_number = f"+{phone_number}"
        elif len(phone_number) < 10:
            raise ValidationError("Please provide a valid phone number.")
        return phone_number

class OwnerRegistrationForm(UserCreationForm):
    company_name = forms.CharField(
        label="Company Name",
        widget=forms.TextInput(attrs={'placeholder': 'Company Name', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        error_messages={
            'required': 'Company name is required.'
        }
    )
    company_short_name = forms.CharField(
        label="Company Short Name",
        max_length=5,
        widget=forms.TextInput(attrs={'placeholder': 'Company abbreviation', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        error_messages={
            'required': 'Company name abbreviation is required.',
            'max_length': 'Short name cannot exceed 5 characters.'
        }
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'placeholder': 'Email', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        error_messages={
            'required': 'Email address is required.',
            'invalid': 'Please enter a valid email address.'
        }
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'email', 'password1', 'password2', 'company_name', 'company_short_name']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Username', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'password1': forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'password2': forms.PasswordInput(attrs={'placeholder': 'Confirm Password', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        }
        error_messages = {
            'username': {
                'required': 'Username is required.',
                'unique': 'This username is already taken.',
                'invalid': 'Please enter a valid username.'
            },
            'first_name': {
                'required': 'Your first name is required',
            },
            'password2': {
                'required': 'Please confirm your password.',
                'password_mismatch': 'Passwords do not match.'
            }
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise ValidationError("This email address is already in use.")
        return email

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        if password1:
            try:
                validate_password(password1, self.instance)
            except ValidationError as e:
                raise ValidationError(e.messages)
        return password1

class ManagerRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'placeholder': 'Email', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        error_messages={
            'required': 'Email address is required.',
            'invalid': 'Please enter a valid email address.'
        }
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'email', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Username', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'password1': forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
            'password2': forms.PasswordInput(attrs={'placeholder': 'Confirm Password', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-dark-primary'}),
        }
        error_messages = {
            'username': {
                'required': 'Username is required.',
                'unique': 'This username is already taken.',
                'invalid': 'Please enter a valid username.'
            },
            'password2': {
                'required': 'Please confirm your password.',
                'password_mismatch': 'Passwords do not match.'
            }
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise ValidationError("This email address is already in use.")
        return email

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        if password1:
            try:
                validate_password(password1, self.instance)
            except ValidationError as e:
                raise ValidationError(e.messages)
        return password1


class SkillForm(forms.ModelForm):
    class Meta:
        model = LaborType
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'autofocus': 'autofocus', 'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}),
        }


class CompanyForm(forms.ModelForm):
    name = forms.CharField(
        label="Company Name",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    address = forms.CharField(
        label="Address",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    city = forms.CharField(
        label="City",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    state = forms.CharField(
        label="State",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    zip_code= forms.CharField(
        label="Zip Code",
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
    class Meta:
        model = Company
        fields = [ 'name', 'address', 'city', 'state', 'zip_code', 'phone_number', 'email', 'website',]


class CompanyHoursForm(forms.ModelForm):
    minimum_hours = forms.IntegerField(
        label="Minimum Call Time Hours",
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    meal_penalty_trigger_time = forms.IntegerField(
        label="Meal Penalty Trigger Time (Hours)",
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    hour_round_up = forms.IntegerField(
        label="Minutes to round to next half hour",
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    class Meta:
        model = Company
        fields = ['minimum_hours', 'meal_penalty_trigger_time', 'hour_round_up']


class LocationProfileForm(forms.ModelForm):
    name = forms.CharField(
        label="Location Name",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    address = forms.CharField(
        label="Address",
        required=False,
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    minimum_hours = forms.IntegerField(
        label="Minimum Call Time Hours",
        required=False,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    meal_penalty_trigger_time = forms.IntegerField(
        label="Meal Penalty Trigger Time (Hours)",
        required=False,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    hour_round_up = forms.IntegerField(
        label="Minutes to round to next half hour",
        required=False,
        widget=forms.NumberInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    class Meta:
        model = LocationProfile
        fields = ['name', 'address', 'minimum_hours', 'meal_penalty_trigger_time', 'hour_round_up']

class AddWorkerForm(forms.ModelForm):
    phone_number = forms.CharField(
        label="Phone Number",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border', 'placeholder': 'Phone Number'}),
        error_messages={
            'required': 'Phone number is required.',
            'invalid': 'Please provide a valid phone number.'
        }
    )

    class Meta:
        model = Worker
        fields = ['name', 'phone_number']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border', 'placeholder': 'Name'}),
        }
        error_messages = {
            'name': {
                'required': 'Name is required.',
            }
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        phone_number = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if len(phone_number) == 10:
            phone_number = f"+1{phone_number}"
        elif len(phone_number) == 11 and phone_number.startswith('1'):
            phone_number = f"+{phone_number}"
        elif len(phone_number) < 10:
            raise ValidationError("Please provide a valid phone number.")
        if self.company and Worker.objects.filter(phone_number=phone_number, companies=self.company).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise ValidationError("You're already in our system. Thanks!")
        return phone_number

class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(
        label="Old Password",
        widget=forms.PasswordInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
    class Meta:
        fields = ['old_password', 'new_password1', 'new_password2']
        labels = {
            'old_password': 'Old Password',
            'new_password1': 'New Password',
            'new_password2': 'Confirm New Password',
        }
        error_messages = {
            'old_password': {
                'required': 'Old password is required.',
            },
            'new_password1': {
                'required': 'New password is required.',
            },
            'new_password2': {
                'required': 'Please confirm your new password.',
                'password_mismatch': 'Passwords do not match.'
            }
        }
    def clean_new_password1(self):
        password = self.cleaned_data.get('new_password1')
        if password:
            validate_password(password)
        return password
    
    def clean(self):
        cleaned_data = super().clean()
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')
        if new_password1 and new_password2 and new_password1 != new_password2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

class AdminLoginForm(forms.Form):
    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(attrs={'class': 'w-full p-2 border rounded bg-card-bg text-text-tertiary dark:bg-dark-card-bg dark:text-dark-text-tertiary dark:border-dark-border'}))
