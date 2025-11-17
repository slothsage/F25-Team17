from django import forms
from .models import DriverProfile
from .models import Message
from .models import DriverNotificationPreference
from .models import CustomLabel
from .models import SecurityQuestion, UserSecurityAnswer
from .models import SponsorProfile
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.contrib.auth.password_validation import password_validators_help_text_html
from .models import SponsorPointsAccount

User = get_user_model()

class ProfileForm(forms.ModelForm):
    """Basic profile form without image field to avoid upload issues."""
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = DriverProfile
        fields = [
            "first_name",
            "last_name",
            "phone",
            "address",
            "city",
            "state",
            "zip_code",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Tell sponsors a bit about yourself…"}
            ),
        }

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


class ProfilePictureForm(forms.ModelForm):
    """Separate form for profile picture uploads."""
    class Meta:
        model = DriverProfile
        fields = ["image"]
        widgets = {
            "image": forms.FileInput(attrs={
                "accept": "image/*",
                "class": "form-control"
            })
        }

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if not img:
            return img
        
        # Check file size
        if img.size > 5 * 1024 * 1024:  # 5MB limit
            raise forms.ValidationError("File size is too large ( > 5MB ).")
        
        # Check file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if hasattr(img, 'content_type') and img.content_type not in allowed_types:
            raise forms.ValidationError("Please upload a valid image file (JPEG, PNG, GIF, or WebP).")
        
        return img


class AdminProfileForm(forms.ModelForm):
    """Admin version of ProfileForm without image field to avoid Pillow dependency issues."""
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = DriverProfile
        fields = [
            "first_name",
            "last_name",
            "phone",
            "address",
            "city",
            "state",
            "zip_code",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "placeholder": "Tell sponsors a bit about yourself…"}
            ),
        }

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

class MessageComposeForm(forms.ModelForm):
    select_all = forms.BooleanField(required=False, label="All Users")
    include_admins = forms.BooleanField(required=False, label="Admins")
    include_sponsors = forms.BooleanField(required=False, label="Sponsors")
    include_drivers = forms.BooleanField(required=False, label="Drivers")

    users = forms.ModelMultipleChoiceField(
        queryset = User.objects.filter(is_active=True).order_by("username"),
        required = False,
        help_text = "Select specific users to send to (overrides other selections).",
    )
    
    class Meta:
        model = Message
        fields = [
            "subject",
            "body",
            "select_all",
            "include_admins",
            "include_sponsors",
            "include_drivers",
            "users",
        ]

"""
    def clean(self):
        cleaned = super().clean()
        if not (
            cleaned.get("select_all") or
            cleaned.get("include_admins") or
            cleaned.get("include_sponsors") or
            cleaned.get("include_drivers") or
            cleaned.get("users")
        ):
            raise forms.ValidationError("Please select at least one recipient.")
        return cleaned
"""

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

class SecurityQuestionsForm(forms.Form):
    """Three sec. questiosns & collecting answers"""
    q_pet = forms.CharField(
        label="What was the name of your childhood pet?", 
        max_length=255, 
        widget=forms.PasswordInput(render_value=True))
    q_color = forms.CharField(label="What is your favorite color?", 
        max_length=255, 
        widget=forms.PasswordInput(render_value=True))
    q_school = forms.CharField(label="Where did you attend high school?", 
        max_length=255, 
        widget=forms.PasswordInput(render_value=True))
    
    def save(self, user):
        mapping = {
            "q_pet": "pet_name",
            "q_color": "favorite_color",
            "q_school": "high_school",
        }
        for field, code in mapping.items():
            question = SecurityQuestion.objects.get(code=code)
            ans, _ = UserSecurityAnswer.objects.get_or_create(user=user, question=question)
            ans.set_answer(self.cleaned_data[field])
            ans.save()
        return True

class PolicyPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].help_text = password_validators_help_text_html()

class AddressForm(forms.ModelForm):
    class Meta:
        model = DriverProfile
        fields = ["address"]
        widgets = {
            "address": forms.TextInput(attrs={
                "placeholder": "Delivery address",
                "style": "min-width: 320px;"
            })
        }

class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = DriverNotificationPreference
        fields = ["orders", "points", "promotions", "email_enabled", "sms_enabled", "sound_mode", "sound_file", "theme", "language", "low_balance_threshold", "low_balance_alert_enabled"]
        widgets = {
            "orders": forms.CheckboxInput(),
            "points": forms.CheckboxInput(),
            "promotions": forms.CheckboxInput(),
            "email_enabled": forms.CheckboxInput(),
            "sms_enabled": forms.CheckboxInput(),
            "theme": forms.Select(),
            "low_balance_alert_enabled": forms.CheckboxInput(),
            "low_balance_threshold": forms.NumberInput(attrs={"min": 0, "step": 5}),
        }
        labels = {
            "email_enabled": "Email alerts",
            "sms_enabled": "SMS alerts (preferred; no duplicate emails)",
            "theme": "Theme",
            "low_balance_alert_enabled": "Warn me when my points are low",
            "low_balance_threshold": "Low balance threshold (points)",
        }

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("sound_mode")
        file = cleaned.get("sound_file")
        if mode == "custom" and not file:
            self.add_error("sound_file", "Please upload an audio file for custom sound.")
        if mode in ("default", "silent"):
            cleaned["sound_file"] = None
        thresh = cleaned.get("low_balance_threshold")
        if thresh is not None and thresh < 0:
            self.add_error("low_balance_threshold", "Threshold must be 0 or higher.")
        return cleaned
    

class ContactSponsorForm(forms.Form):
    subject = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Subject"}),
        label="Subject"
    )
    message = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 5, "placeholder": "Your message..."}),
        label="Message"
    )

class PointsGoalForm(forms.Form):
    points_goal = forms.IntegerField(
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "1"}),
        label="Points Goal",
        help_text="Set your personal points goal to track your progress"
    )

class LabelForm(forms.ModelForm):
    """Create or edit a label."""
    class Meta:
        model = CustomLabel
        fields = ["name", "color"]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color", "style": "width: 90px;"}),
            "name": forms.TextInput(attrs={"placeholder": "Label name"}),
        }


class AssignLabelForm(forms.Form):
    """Assign one or more labels to a driver."""
    from .models import DriverProfile
    driver = forms.ModelChoiceField(
        queryset=DriverProfile.objects.select_related("user").order_by("user__username"),
        label="Select driver",
    )
    labels = forms.ModelMultipleChoiceField(
        queryset=CustomLabel.objects.all().order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Assign labels",
    )

"""
class SponsorApplicationForm(forms.Form):
    sponsor = forms.ModelChoiceField(
        queryset=User.objects.filter(groups__name="sponsor").order_by("username"),
        help_text="Choose a sponsor to apply to.",
    )
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        self.driver = kwargs.pop("driver", None)
        super().__init__(*args, **kwargs)
        # excludes sponsors if driver has an app w/:
        if self.driver is not None:
            self.fields["sponsor"].queryset = self.fields["sponsor"].queryset.exclude(
                driver_applications__driver=self.driver
            )
"""

class SponsorAwardForm(forms.Form):
    driver_id = forms.IntegerField(widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=[("award", "Award"), ("deduct", "Deduct")])
    amount = forms.IntegerField(min_value=1)
    reason = forms.CharField(required=False, max_length=255)

    def clean_amount(self):
        amt = self.cleaned_data["amount"]
        if amt <= 0:
            raise forms.ValidationError("Amount must be a positive integer.")
        return amt

    def delta(self):
        amt = self.cleaned_data["amount"]
        return amt if self.cleaned_data["action"] == "award" else -amt
    
class SponsorFeeRatioForm(forms.ModelForm):
    """Form for admins to set fee ratio (points per USD) for a sponsor."""
    class Meta:
        model = SponsorProfile
        fields = ["points_per_usd"]
        widgets = {
            "points_per_usd": forms.NumberInput(attrs={
                "min": 1,
                "step": 1,
                "class": "form-control",
                "placeholder": "Leave blank to use global default"
            })
        }
        labels = {
            "points_per_usd": "Points per USD (Fee Ratio)"
        }
        help_texts = {
            "points_per_usd": "How many points this sponsor awards per $1. Leave blank to use the global default."
        }
    
    def clean_points_per_usd(self):
        value = self.cleaned_data.get("points_per_usd")
        if value is not None and value < 1:
            raise forms.ValidationError("Points per USD must be at least 1.")
        return value

class SetPrimaryWalletForm(forms.Form):
    wallet_id = forms.ModelChoiceField(queryset=SponsorPointsAccount.objects.none())

    def __init__(self, *args, **kwargs):
        driver = kwargs.pop("driver")
        super().__init__(*args, **kwargs)
        self.fields["wallet_id"].queryset = SponsorPointsAccount.objects.filter(driver=driver)