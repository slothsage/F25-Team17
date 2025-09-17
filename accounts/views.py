from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.shortcuts import render, redirect, get_object_or_404
from .models import DriverProfile
from .forms import ProfileForm, DeleteAccountForm

@login_required
def profile(request):
    DriverProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/profile.html")

@login_required
def profile_edit(request):
    profile, _ = DriverProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("profile")
    else:
        form = ProfileForm(instance=profile, user=request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})

@login_required
def profile_preview(request):
    # Sponsor-visible projection 
    profile = getattr(request.user, "driver_profile", None)
    data = {
        "username": request.user.username,
        "email": request.user.email,
        "phone": profile.phone if profile else "",
        "address": profile.address if profile else "",
        "join_status": "approved",  
    }
    return render(request, "accounts/profile_preview.html", {"data": data})

@login_required
def delete_account(request):
    if request.method == "POST":
        form = DeleteAccountForm(request.POST)
        if form.is_valid():
            # Delete user (cascades to DriverProfile)
            user = request.user
            auth_logout(request)
            user.delete()
            messages.success(request, "Your account has been deleted.")
            return redirect("login")
    else:
        form = DeleteAccountForm()
    return render(request, "accounts/delete_account.html", {"form": form})