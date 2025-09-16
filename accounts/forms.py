from django import forms
from .models import DriverProfile

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