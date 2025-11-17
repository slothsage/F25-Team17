from django import forms
from .models import PointsConfig, SponsorCatalogItem, DriverCatalogItem

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
    ship_name   = forms.CharField(label="Full Name", max_length=200, widget=forms.TextInput(attrs={"class": "form-control"}))
    ship_line1  = forms.CharField(label="Address Line 1", max_length=200, widget=forms.TextInput(attrs={"class": "form-control"}))
    ship_line2  = forms.CharField(label="Address Line 2", max_length=200, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    ship_city   = forms.CharField(label="City", max_length=100, widget=forms.TextInput(attrs={"class": "form-control"}))
    ship_state  = forms.CharField(label="State/Province", max_length=100, widget=forms.TextInput(attrs={"class": "form-control"}))
    ship_postal = forms.CharField(label="Postal Code", max_length=20, widget=forms.TextInput(attrs={"class": "form-control"}))
    ship_country = forms.CharField(label="Country Code", max_length=2, initial="US", widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "US"}))

class SponsorCatalogItemForm(forms.ModelForm):
    class Meta:
        model = SponsorCatalogItem
        fields = [
            "name",
            "description",
            "price_usd",
            "points_cost",
            "image_url",
            "product_url",
            "category",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "required": True}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "price_usd": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "points_cost": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "image_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "product_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "category": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "price_usd": "Price (USD)",
            "points_cost": "Points Cost",
            "image_url": "Image URL",
            "product_url": "Product URL",
            "is_active": "Active (visible in catalog)",
        }
