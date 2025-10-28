# shop/forms.py
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
