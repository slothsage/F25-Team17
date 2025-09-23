from django import forms
from .models import DriverProfile
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.contrib.auth.password_validation import password_validators_help_text_html

User = get_user_model()

class ProfileForm(forms.ModelForm):
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = DriverProfile
        fields = ["phone", "address"]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["email"].initial = self.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.email = self.cleaned_data["email"]
        if commit:
            self.user.save(update_fields=["email"])
            profile.user = self.user
            profile.save()
        return profile


class DeleteAccountForm(forms.Form):
    confirm = forms.CharField(
        required=True,
        label="Type DELETE to confirm",
        help_text='This will permanently delete your account.'
    )

    def clean_confirm(self):
        v = self.cleaned_data["confirm"].strip().upper()
        if v != "DELETE":
            raise forms.ValidationError('Please type DELETE to confirm.')
        return v
    

class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Surface rules coming from AUTH_PASSWORD_VALIDATORS (incl. your custom one)
        self.fields["password1"].help_text = password_validators_help_text_html()


class PolicyPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = password_validators_help_text_html()