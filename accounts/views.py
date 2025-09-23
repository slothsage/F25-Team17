from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.mail import send_mail

from .forms import RegistrationForm  
from .models import PasswordPolicy
from .models import DriverProfile
from .forms import ProfileForm, DeleteAccountForm

User = get_user_model()

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


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account created. You can now log in.")
            return redirect("login")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


@staff_member_required
def edit_policy(request):
    policy = PasswordPolicy.objects.order_by("-updated_at").first() or PasswordPolicy()
    if request.method == "POST":
        def b(name): return request.POST.get(name) == "on"
        def n(name): return int(request.POST.get(name) or 0)
        policy.min_length     = n("min_length")
        policy.require_upper  = b("require_upper")
        policy.require_lower  = b("require_lower")
        policy.require_digit  = b("require_digit")
        policy.require_symbol = b("require_symbol")
        policy.expiry_days    = n("expiry_days")
        policy.save()
        messages.success(request, "Password policy updated.")
        return redirect("accounts:edit_policy")
    return render(request, "accounts/policy_form.html", {"policy": policy})


@staff_member_required
def send_reset_link(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = request.build_absolute_uri(reverse("password_reset_confirm", args=[uidb64, token]))
    send_mail(
        subject="Password reset",
        message=f"Use this link to reset your password: {url}",
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
    )
    messages.success(request, f"Reset link emailed to {user.email}.")
    return redirect(request.META.get("HTTP_REFERER", "admin:index"))

@staff_member_required
def set_temporary_password(request, user_id):
    # Only if your stories require temp passwords; reset links are safer.
    import secrets, string
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    temp = "".join(secrets.choice(alphabet) for _ in range(16))
    user.set_password(temp)
    user.save()
    send_mail(
        subject="Temporary password",
        message=f"Your temporary password: {temp}\nPlease change it after login.",
        from_email=None,
        recipient_list=[user.email],
    )
    messages.success(request, f"Temporary password emailed to {user.email}.")
    return redirect(request.META.get("HTTP_REFERER", "admin:index"))
