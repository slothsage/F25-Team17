from django import forms
from .models import PointsConfig

class PointsConfigForm(forms.ModelForm):
    class Meta:
        model = PointsConfig
        fields = ["points_per_usd"]
        widgets = {
            "points_per_usd": forms.NumberInput(attrs={
                "min": 1, "step": 1, "class": "input"
            })
        }
        help_texts = {
            "points_per_usd": "How many points a user earns per $1 (must be a positive integer)."
        }

    def clean_points_per_usd(self):
        v = self.cleaned_data["points_per_usd"]
        if v < 1:
            raise forms.ValidationError("Points per USD must be at least 1.")
        return v
    
class CheckoutForm(forms.Form):
    ship_name   = forms.CharField(label="Full Name", max_length=200)
    ship_line1  = forms.CharField(label="Address Line 1", max_length=200)
    ship_line2  = forms.CharField(label="Address Line 2", max_length=200, required=False)
    ship_city   = forms.CharField(label="City", max_length=100)
    ship_state  = forms.CharField(label="State/Province", max_length=100)
    ship_postal = forms.CharField(label="Postal Code", max_length=20)
    ship_country = forms.CharField(label="Country Code", max_length=2, initial="US")
