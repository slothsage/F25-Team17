from multiprocessing import context
from django.contrib import messages
from django import forms
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import logout as auth_logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.mail import send_mail
from django.db.models.functions import TruncDate
from django.db import connections
from django.utils import timezone
import datetime
import os
from datetime import timedelta
from django.db.models import Sum
from urllib.parse import quote
from django.templatetags.static import static
from django.utils.timezone import now
from django.utils.timezone import localtime
from urllib3 import request

from .forms import RegistrationForm  
from .models import PasswordPolicy, LockoutPolicy
from .models import DriverProfile, SponsorProfile
from .models import ChatRoom, ChatMessage, MessageReadStatus
from .models import Notification
from .models import PointsLedger
from .models import Message, MessageRecipient
from .models import FailedLoginAttempt
from .models import SecurityQuestion, UserSecurityAnswer
from .forms import MessageComposeForm
from .forms import NotificationPreferenceForm
from .forms import SecurityQuestionsForm

from .forms import ProfileForm, AdminProfileForm, DeleteAccountForm, ProfilePictureForm
from .models import DriverNotificationPreference
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Q
from django import db as django_db
from django.db import models
from .models import LoginActivity
from shop.models import Order
from shop.utils import order_is_delayed
from django.core.paginator import Paginator
from django.http import HttpResponse
import csv
from io import BytesIO
from django.template.loader import render_to_string
try:
    from xhtml2pdf import pisa
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from django.contrib.auth.views import LoginView
from django.shortcuts import resolve_url
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django import forms
from django.contrib.admin.views.decorators import staff_member_required

from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth import get_user_model

from django.http import HttpResponseRedirect
from django.urls import reverse

from django.http import FileResponse, HttpResponseNotFound
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required

import csv
from io import StringIO, TextIOWrapper
from django.contrib.auth.models import Group
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required

from .models import LoginActivity, PointChangeLog, PasswordChangeLog, DriverApplicationLog
from .models import SponsorshipRequest, SponsorPointsAccount, SponsorPointsTransaction
from .models import BulkUploadLog
import io, base64, pyotp, qrcode
from django.contrib.auth import login as auth_login
from django.views.decorators.csrf import csrf_protect

from django.contrib.auth.views import PasswordChangeView, PasswordResetConfirmView
from django.contrib import messages
from .services import notify_password_change, get_driver_points_balance
from .forms import LabelForm, AssignLabelForm
from .models import CustomLabel, DriverProfile

from django.db import transaction
from .models import SponsorPointsAccount
from .forms import SponsorAwardForm, SetPrimaryWalletForm, ContactSponsorForm, PointsGoalForm, SponsorFeeRatioForm
from django.db.models import OuterRef, Subquery, IntegerField

User = get_user_model()

def _user_in_group(user, group_name: str) -> bool:
    return user.is_authenticated and user.groups.filter(name=group_name).exists()

def _require_group(user, g):
    return user.is_authenticated and user.groups.filter(name__iexact=g).exists()

def _sponsor_required(user):
    """
    Returns True if the user is allowed to access sponsor-only pages.
    Treats superusers as allowed as well.
    """
    return bool(
        user.is_authenticated and (
            user.is_superuser or user.groups.filter(name="sponsor").exists()
        )
    )

try:
    from shop.models import Sponsor
    HAS_SPONSOR_MODEL = True
except Exception:
    Sponsor = None
    HAS_SPONSOR_MODEL = False

def _field_exists(model, name: str) -> bool:
    return any(f.name == name for f in model._meta.get_fields())

def _parse_date_yyyy_mm_dd(s: str):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

@login_required
def audit_report(request):
    """
    Reporting – Audit Log
    Roles: Admin or Sponsor
    Filters: sponsor (admin only can pick 'All' or one sponsor), date range, category, user_id
    Categories: login_attempts, point_changes, password_changes, driver_applications
    CSV export: add ?format=csv
    Sponsor users ONLY see data for their own sponsor organization.
    """
    user = request.user
    is_admin = user.is_staff

    # --- Inputs ---
    category = (request.GET.get("category", "login_attempts") or "").strip() or "login_attempts"
    start_str = (request.GET.get("start") or "").strip()
    end_str = (request.GET.get("end") or "").strip()
    sponsor_param = (request.GET.get("sponsor") or "").strip()
    user_id_str = (request.GET.get("user_id") or "").strip()
    want_csv = (request.GET.get("format") or "").lower() == "csv"

    # Parse user_id (empty/invalid -> None)
    user_id = None
    if user_id_str.isdigit():
        try:
            user_id = int(user_id_str)
        except ValueError:
            user_id = None

    # --- Sponsor scoping & sponsor options list ---
    sponsor_names = (
        DriverProfile.objects.exclude(sponsor_name="")
        .values_list("sponsor_name", flat=True)
        .distinct()
        .order_by("sponsor_name")
    )

    if is_admin:
        sponsor_scope = sponsor_param  # '' means all sponsors
    else:
        sponsor_scope = getattr(getattr(user, "driver_profile", None), "sponsor_name", "") or ""
        sponsor_param = sponsor_scope

    # --- Date range (defaults: last 30 days) ---
    today = timezone.localdate()
    start_date = _parse_date_yyyy_mm_dd(start_str) or (today - timedelta(days=30))
    end_date = _parse_date_yyyy_mm_dd(end_str) or today

    # normalize to datetimes for DB range filtering
    start_dt = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
    end_dt   = timezone.make_aware(datetime.datetime.combine(end_date,   datetime.time.max))

    columns, rows = [], []

    # Helper to selectively sponsor-filter a queryset by driver’s sponsor name
    def filter_by_sponsor_via_driver(qs, driver_field="user"):
        if not sponsor_scope:
            return qs
        return qs.filter(**{f"{driver_field}__driver_profile__sponsor_name": sponsor_scope})

    # --- Build dataset per category ---
    if category == "login_attempts":
        qs = LoginActivity.objects.filter(created_at__range=(start_dt, end_dt))

        # Sponsor scoping
        if sponsor_scope:
            sponsor_usernames = list(
                DriverProfile.objects.filter(sponsor_name=sponsor_scope, user__isnull=False)
                .values_list("user__username", flat=True)
            )
            qs = qs.filter(
                Q(user__driver_profile__sponsor_name=sponsor_scope) |
                Q(username__in=sponsor_usernames)
            )

        # User ID filter: match either the resolved user FK or the attempted username
        if user_id:
            try:
                target_user = User.objects.get(id=user_id)
                qs = qs.filter(Q(user_id=user_id) | Q(username=target_user.username))
            except User.DoesNotExist:
                qs = qs.none()

        qs = qs.select_related("user").order_by("-created_at")
        columns = ["Date", "Username", "Success", "IP"]
        for rec in qs:
            rows.append([
                timezone.localtime(rec.created_at).strftime("%Y-%m-%d %H:%M"),
                (rec.user.username if rec.user else rec.username) or "",
                "OK" if rec.successful else "FAIL",
                rec.ip_address or "",
            ])

    elif category == "point_changes":
        qs = PointChangeLog.objects.filter(created_at__range=(start_dt, end_dt))

        # Sponsor scoping
        if sponsor_scope:
            if _field_exists(PointChangeLog, "sponsor_name"):
                qs = qs.filter(sponsor_name=sponsor_scope)
            else:
                qs = filter_by_sponsor_via_driver(qs, driver_field="driver")

        # User ID filter (driver)
        if user_id:
            qs = qs.filter(driver_id=user_id)

        qs = qs.select_related("driver").order_by("-created_at")
        columns = ["Date", "Sponsor", "Driver", "Points", "Reason"]
        for rec in qs:
            sponsor_name = getattr(rec, "sponsor_name", "") or getattr(
                getattr(rec.driver, "driver_profile", None), "sponsor_name", ""
            )
            rows.append([
                timezone.localtime(rec.created_at).strftime("%Y-%m-%d %H:%M"),
                sponsor_name or "",
                rec.driver.username if rec.driver_id else "",
                rec.points_changed,
                rec.reason or "",
            ])

    elif category == "password_changes":
        qs = PasswordChangeLog.objects.filter(created_at__range=(start_dt, end_dt))
        qs = filter_by_sponsor_via_driver(qs, driver_field="user")

        # User ID filter (user)
        if user_id:
            qs = qs.filter(user_id=user_id)

        qs = qs.select_related("user").order_by("-created_at")
        columns = ["Date", "User", "Type"]
        for rec in qs:
            rows.append([
                timezone.localtime(rec.created_at).strftime("%Y-%m-%d %H:%M"),
                rec.user.username if rec.user_id else "",
                rec.change_type,
            ])

    elif category == "driver_applications":
        qs = DriverApplicationLog.objects.filter(created_at__range=(start_dt, end_dt))

        # Sponsor scoping
        if sponsor_scope:
            if _field_exists(DriverApplicationLog, "sponsor_name"):
                qs = qs.filter(sponsor_name=sponsor_scope)
            else:
                qs = filter_by_sponsor_via_driver(qs, driver_field="driver")

        # User ID filter (driver)
        if user_id:
            qs = qs.filter(driver_id=user_id)

        qs = qs.select_related("driver").order_by("-created_at")
        has_sponsor_name = _field_exists(DriverApplicationLog, "sponsor_name")
        columns = ["Date", "Sponsor", "Driver", "Status", "Reason"]
        for rec in qs:
            sponsor_name = (
                getattr(rec, "sponsor_name", None)
                if has_sponsor_name
                else getattr(getattr(rec.driver, "driver_profile", None), "sponsor_name", None)
            ) or ""
            rows.append([
                timezone.localtime(rec.created_at).strftime("%Y-%m-%d %H:%M"),
                sponsor_name,
                rec.driver.username if rec.driver_id else "",
                rec.status,
                rec.reason or "",
            ])

    elif category == "impersonations":
        from .models import ImpersonationLog
        qs = ImpersonationLog.objects.filter(started_at__range=(start_dt, end_dt))

        # Admin users can see all impersonations, sponsors see none (admin-only feature)
        if not is_admin:
            qs = qs.none()

        # User ID filter (can filter by admin or impersonated user)
        if user_id:
            qs = qs.filter(Q(admin_user_id=user_id) | Q(impersonated_user_id=user_id))

        qs = qs.select_related("admin_user", "impersonated_user").order_by("-started_at")
        columns = ["Date", "Admin", "Impersonated User", "Duration", "IP Address"]
        for rec in qs:
            duration_str = ""
            if rec.duration_seconds is not None:
                minutes, seconds = divmod(rec.duration_seconds, 60)
                hours, minutes = divmod(minutes, 60)
                if hours > 0:
                    duration_str = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    duration_str = f"{minutes}m {seconds}s"
                else:
                    duration_str = f"{seconds}s"
            else:
                duration_str = "Active" if not rec.ended_at else "Unknown"
            
            rows.append([
                timezone.localtime(rec.started_at).strftime("%Y-%m-%d %H:%M"),
                rec.admin_user.username if rec.admin_user_id else "",
                rec.impersonated_user.username if rec.impersonated_user_id else "",
                duration_str,
                rec.ip_address or "",
            ])

    context = {
        "title": "Audit Report",
        "is_admin": is_admin,
        "category": category,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "sponsor": sponsor_param,
        "sponsor_names": sponsor_names,
        "user_id": user_id_str,
        "columns": columns,
        "rows": rows,
    }

    # CSV export
    if want_csv:
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([str(c) if c is not None else "" for c in r])
        filename = f"audit_{category}_{start_date.isoformat()}_{end_date.isoformat()}.csv"
        response = HttpResponse(buf.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return render(request, "accounts/audit_report.html", context)


@login_required
def profile(request):
    profile_obj, _ = DriverProfile.objects.get_or_create(user=request.user)
    
    # Only show points for drivers (not sponsors or admins)
    is_driver = hasattr(request.user, "driver_profile")
    is_sponsor = request.user.groups.filter(name="sponsor").exists()
    is_admin = request.user.is_staff or request.user.is_superuser
    show_points = is_driver and not is_sponsor and not is_admin
    
    total_points = None
    progress_percentage = 0
    points_remaining = 0
    has_goal = False
    
    if show_points:
        total_points = get_driver_points_balance(request.user)
        # Calculate progress for goal tracker
        if profile_obj.points_goal and profile_obj.points_goal > 0:
            progress_percentage = min(100, int((total_points / profile_obj.points_goal) * 100))
            points_remaining = max(0, profile_obj.points_goal - total_points)
            has_goal = True
    
    return render(request, "accounts/profile.html", {
        "total_points": total_points,
        "points_goal": profile_obj.points_goal if show_points else None,
        "progress_percentage": progress_percentage,
        "points_remaining": points_remaining,
        "has_goal": has_goal,
        "show_points": show_points,
    })

@login_required
def profile_edit(request):
    profile, _ = DriverProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=profile, user=request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})


@login_required
def profile_picture_edit(request):
    """Separate view for profile picture uploads."""
    profile, _ = DriverProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        # Handle picture removal
        if request.POST.get('remove_picture'):
            if profile.image:
                profile.image.delete()
                profile.image = None
                profile.save()
                messages.success(request, "Profile picture removed successfully!")
                return redirect("accounts:profile")
        else:
            # Handle picture upload
            form = ProfilePictureForm(request.POST, request.FILES, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile picture updated successfully!")
                return redirect("accounts:profile")
    else:
        form = ProfilePictureForm(instance=profile)
    return render(request, "accounts/profile_picture_edit.html", {"form": form, "profile": profile})

@staff_member_required
def admin_profile_edit(request, user_id):
    """Allow staff to edit any user's profile (without image upload to avoid Pillow issues)."""
    target_user = get_object_or_404(User, pk=user_id)
    profile, _ = DriverProfile.objects.get_or_create(user=target_user)
    
    if request.method == "POST":
        form = AdminProfileForm(request.POST, instance=profile, user=target_user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Profile for {target_user.username} updated successfully.")
            return redirect("admin_user_search")
    else:
        form = AdminProfileForm(instance=profile, user=target_user)
    
    return render(request, "accounts/profile_edit.html", {
        "form": form,
        "editing_user": target_user,
        "is_admin_edit": True
    })

@staff_member_required
def transfer_driver_sponsor(request, user_id):
    """Admin: Reassign a driver's sponsor to a valid sponsor user."""
    driver_user = get_object_or_404(User, pk=user_id)
    profile = getattr(driver_user, "driver_profile", None)

    if not profile:
        messages.error(request, "This user has no driver profile.")
        return redirect("admin_user_search")

    # Get actual sponsor users
    sponsor_users = (
        User.objects.filter(groups__name="sponsor")
        .values("username", "email")
        .order_by("username")
    )

    if request.method == "POST":
        sponsor_id = request.POST.get("sponsor_name")
        new_email = request.POST.get("sponsor_email", "").strip()

        if not sponsor_id:
            messages.error(request, "Sponsor selection is required.")
        else:
            try:
                new_sponsor = User.objects.get(username=sponsor_id, groups__name="sponsor")
            except User.DoesNotExist:
                messages.error(request, "Selected sponsor is invalid.")
                return redirect(request.path)

            old_sponsor = profile.sponsor_name or "None"
            profile.sponsor_name = new_sponsor.username
            profile.sponsor_email = new_email or new_sponsor.email
            profile.save()

            # Update orders
            Order.objects.filter(driver=driver_user).update(sponsor_name=new_sponsor.username)

            # Notify driver
            Notification.objects.create(
                user=driver_user,
                kind="system",
                title="Sponsor Reassigned",
                body=f"Your sponsor has been changed from {old_sponsor} to {new_sponsor.username}.",
            )

            messages.success(
                request,
                f"Driver {driver_user.username} reassigned from {old_sponsor} → {new_sponsor.username}.",
            )
            return redirect("admin_user_search")

    return render(
        request,
        "accounts/transfer_driver_sponsor.html",
        {
            "driver": driver_user,
            "profile": profile,
            "sponsor_users": sponsor_users,
        }
    )

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
            return redirect("accounts:login")
    else:
        form = DeleteAccountForm()
    return render(request, "accounts/delete_account.html", {"form": form})


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account created. You can now log in.")
            return redirect("accounts:login")
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
def lockout_rules(request):
    """Configure account lockout policy settings."""
    from .models import LockoutPolicy
    
    policy = LockoutPolicy.get_policy()
    
    if request.method == "POST":
        try:
            policy.max_failed_attempts = int(request.POST.get("max_failed_attempts", 5))
            policy.lockout_duration_minutes = int(request.POST.get("lockout_duration_minutes", 30))
            policy.reset_attempts_after_minutes = int(request.POST.get("reset_attempts_after_minutes", 60))
            policy.enabled = request.POST.get("enabled") == "on"
            policy.save()
            
            messages.success(request, "Lockout policy updated successfully.")
            return redirect("accounts:lockout_rules")
        except (ValueError, TypeError) as e:
            messages.error(request, f"Invalid input: {e}")
    
    return render(request, "accounts/lockout_rules.html", {"policy": policy})


@staff_member_required
def send_reset_link(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = request.build_absolute_uri(reverse("accounts:password_reset_confirm", args=[uidb64, token]))
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


class AdminSetPasswordForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, label="New password")
    confirm = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean(self):
        cleaned = super().clean()
        p = cleaned.get("password")
        c = cleaned.get("confirm")
        if p != c:
            raise forms.ValidationError("Passwords do not match")
        return cleaned


@staff_member_required
def admin_set_password(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    if request.method == "POST":
        form = AdminSetPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["password"])
            user.save()
            # show a simple success page with link back to admin search
            messages.success(request, f"Password updated for {user.username}.")
            return render(request, "accounts/admin_set_password_success.html", {"target_user": user})
    else:
        form = AdminSetPasswordForm()
    return render(request, "accounts/admin_set_password.html", {"form": form, "target_user": user})


class AdminSetTimeoutForm(forms.Form):
    # allow blank to unset and use default
    session_timeout_seconds = forms.IntegerField(label="Session timeout (seconds)", required=False, min_value=30, help_text="Blank = use system default")

@login_required
def security_questions_configure(request):
    """Signed-in users can configure set/update the 3 questions"""
    initial = {}
    if request.method == "GET":
        mapping = {
            "q_pet": "pet_name",
            "q_color": "favorite_color",
            "q_school": "high_school",
        }
        for field, code in mapping.items():
            if UserSecurityAnswer.objects.filter(user=request.user, question__code=code).exists():
                initial[field] = "*****"
        form = SecurityQuestionsForm(initial=initial)
        return render(request, "accounts/security_questions.html", {"form": form})

    #POST
    form = SecurityQuestionsForm(request.POST)
    if form.is_valid():
        form.save(request.user)
        messages.success(request, "Your security questions were updated.")
        return redirect("accounts:security_questions_configure")
    return render(request, "accounts/security_questions.html", {"form": form})


@staff_member_required
def admin_set_timeout(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    profile = getattr(user, "driver_profile", None)
    if request.method == "POST":
        form = AdminSetTimeoutForm(request.POST)
        if form.is_valid():
            val = form.cleaned_data.get("session_timeout_seconds")
            if profile:
                profile.session_timeout_seconds = val if val else None
                profile.save()
            else:
                # if the user has no DriverProfile, create one to store the setting
                from .models import DriverProfile
                profile = DriverProfile.objects.create(user=user, session_timeout_seconds=(val if val else None))
            messages.success(request, f"Session timeout updated for {user.username}.")
            return render(request, "accounts/admin_set_timeout_success.html", {"target_user": user})
    else:
        initial = {"session_timeout_seconds": profile.session_timeout_seconds if profile else None}
        form = AdminSetTimeoutForm(initial=initial)
    return render(request, "accounts/admin_set_timeout.html", {"form": form, "target_user": user})

@login_required
def admin_user_search(request):
    """Admin landing page: search for drivers (users with driver_profile) and sponsors (by sponsor_name on orders).

    Search params:
    - q: text that matches username, email, phone, or address for drivers
    - sponsor: text to match sponsor_name (in orders)

    Renders `accounts/admin_user_search.html` with `drivers`, `sponsors`, and `q` in context.
    """
    # support nav search param `type` -> 'driver'|'sponsor'
    q = request.GET.get("q", "").strip()
    sponsor_q = request.GET.get("sponsor", "").strip()
    sort = request.GET.get("sort", "")
    inactive = request.GET.get("inactive", "")
    label_filter = request.GET.get("label", "").strip()
    nav_type = request.GET.get("type")
    if nav_type == "driver" and q == "":
        q = request.GET.get("q", "").strip()
    if nav_type == "sponsor" and sponsor_q == "":
        sponsor_q = request.GET.get("q", "").strip()

    # Restrict driver searches to Users that have a DriverProfile and are not staff or sponsors
    drivers_qs = User.objects.filter(driver_profile__isnull=False, is_staff=False).exclude(groups__name="sponsor")
    drivers_matching_count = 0
    if q:
        # Support searching by numeric id using either 'id:123' or just '123'
        id_query = None
        if q.lower().startswith("id:"):
            maybe = q.split(":", 1)[1].strip()
            if maybe.isdigit():
                id_query = int(maybe)
        elif q.isdigit():
            id_query = int(q)

        if id_query is not None:
            drivers_qs = drivers_qs.filter(Q(pk=id_query) | Q(username__icontains=q) | Q(email__icontains=q) | Q(driver_profile__phone__icontains=q) | Q(driver_profile__address__icontains=q)).distinct()
        else:
            drivers_qs = drivers_qs.filter(
                Q(username__icontains=q) | Q(email__icontains=q) | Q(driver_profile__phone__icontains=q) | Q(driver_profile__address__icontains=q)
            ).distinct()

    if inactive == "never":
        drivers_qs = drivers_qs.filter(last_login__isnull=True)
    elif inactive == "30days":
        thirty_days_ago = timezone.now() - timedelta(days=30)
        drivers_qs = drivers_qs.filter(last_login__lt=thirty_days_ago)

    if sort == "last_login_desc":
        drivers_qs = drivers_qs.order_by("-last_login")
    elif sort == "last_login_asc":
        drivers_qs = drivers_qs.order_by("last_login")
    elif sort == "sponsor_asc":
        drivers_qs = drivers_qs.order_by("driver_profile__sponsor_name")
    elif sort == "sponsor_desc":
        drivers_qs = drivers_qs.order_by("-driver_profile__sponsor_name")

    # counts: total drivers in system, and matching drivers for this query
    total_drivers_count = User.objects.filter(driver_profile__isnull=False, is_staff=False).exclude(groups__name="sponsor").count()
    drivers_matching_count = drivers_qs.count()

    sponsors = []
    sponsors_matching_count = 0
    # total distinct sponsor names
    total_sponsors_count = Order.objects.exclude(sponsor_name__isnull=True).exclude(sponsor_name__exact="").values("sponsor_name").distinct().count()
    if sponsor_q:
        # find sponsor_name and aggregate counts + sample drivers
        sponsor_rows = (
            Order.objects.filter(sponsor_name__icontains=sponsor_q)
            .values("sponsor_name")
            .annotate(count=models.Count("id"))
            .order_by("sponsor_name")
        )
        # build a list with sponsor, count, and sample drivers
        sponsors = []
        for row in sponsor_rows:
            name = row["sponsor_name"]
            count = row["count"]
            drivers = (
                User.objects.filter(orders__sponsor_name=name).distinct().values_list("username", flat=True)[:5]
            )
            sponsors.append({"name": name, "count": count, "drivers": list(drivers)})
        sponsors_matching_count = sponsor_rows.count()

    sponsor_users_qs = User.objects.filter(groups__name="sponsor")
    # Exclude archived sponsors from regular search
    sponsor_users_qs = sponsor_users_qs.exclude(
        sponsor_profile__is_archived=True
    )
    if sponsor_q:
        sponsor_users_qs = sponsor_users_qs.filter(
            Q(username__icontains=sponsor_q) |
            Q(email__icontains=sponsor_q)
        )
    sponsor_users_qs = sponsor_users_qs.order_by("username")

    # Admin users search (staff members)
    admin_q = request.GET.get("admin", "").strip()
    admin_users_qs = User.objects.filter(is_staff=True)
    if admin_q:
        admin_users_qs = admin_users_qs.filter(
            Q(username__icontains=admin_q) |
            Q(email__icontains=admin_q) |
            Q(first_name__icontains=admin_q) |
            Q(last_name__icontains=admin_q)
        )
    admin_users_qs = admin_users_qs.order_by("username")
    admin_users_matching_count = admin_users_qs.count()
    total_admin_users_count = User.objects.filter(is_staff=True).count()
    
    if label_filter:
        drivers_qs = drivers_qs.filter(driver_profile__labels__name=label_filter)

    labels = CustomLabel.objects.all().order_by("name") 

    # simple pagination for drivers
    page_number = request.GET.get("page", 1)
    paginator = Paginator(drivers_qs, 25)
    drivers_page = paginator.get_page(page_number)

    # CSV export
    export = request.GET.get("export")
    export_type = request.GET.get("export_type", "drivers")
    if export == "csv":
        response = HttpResponse(content_type="text/csv")
        filename = "export"
        if export_type == "drivers":
            filename = "drivers_export"
        elif export_type == "sponsors":
            filename = "sponsors_export"
        else:
            filename = "drivers_and_sponsors_export"
        response["Content-Disposition"] = f"attachment; filename=\"{filename}.csv\""
        writer = csv.writer(response)

        # write driver rows
        if export_type in ("drivers", "both"):
            writer.writerow(["record_type", "id", "username", "email", "phone", "address", "last_login", "is_active"])
            for u in drivers_qs.order_by("username").distinct():
                phone = getattr(getattr(u, "driver_profile", None), "phone", "")
                address = getattr(getattr(u, "driver_profile", None), "address", "")
                last_login = u.last_login.isoformat() if u.last_login else ""
                writer.writerow(["driver", u.id, u.username, u.email, phone, address, last_login, str(u.is_active)])

        # write sponsor rows
        if export_type in ("sponsors", "both"):
            if export_type == "both":
                writer.writerow([])
            writer.writerow(["record_type", "sponsor_name", "sample_drivers"])
            if sponsor_q:
                sponsor_rows = (
                    Order.objects.filter(sponsor_name__icontains=sponsor_q)
                    .values("sponsor_name")
                    .annotate(count=models.Count("id"))
                    .order_by("sponsor_name")
                )
            else:
                sponsor_rows = (
                    Order.objects.exclude(sponsor_name__isnull=True)
                    .exclude(sponsor_name__exact="")
                    .values("sponsor_name")
                    .annotate(count=models.Count("id"))
                    .order_by("sponsor_name")
                )

            for row in sponsor_rows:
                name = row["sponsor_name"]
                count = row["count"]
                drivers = User.objects.filter(orders__sponsor_name=name).distinct().values_list("username", flat=True)[:5]
                writer.writerow(["sponsor", name, count, ", ".join(drivers)])

        return response

    failed_logins = FailedLoginAttempt.objects.order_by('-timestamp')[:25]

    return render(
        request,
        "accounts/admin_user_search.html",
        {
            "drivers": drivers_page,
            "labels": labels,
            "selected_label": label_filter,
            "sponsors": sponsors,
            "sponsor_users": sponsor_users_qs,
            "admin_users": admin_users_qs,
            "q": q,
            "sponsor_q": sponsor_q,
            "admin_q": admin_q,
            "total_drivers_count": total_drivers_count,
            "drivers_matching_count": drivers_matching_count,
            "total_sponsors_count": total_sponsors_count,
            "sponsors_matching_count": sponsors_matching_count,
            "total_admin_users_count": total_admin_users_count,
            "admin_users_matching_count": admin_users_matching_count,
            "failed_logins": failed_logins,  
        },
    )


@staff_member_required
def admin_detail(request, user_id):
    """Display detailed information about an admin user."""
    User = get_user_model()
    admin_user = get_object_or_404(User, pk=user_id, is_staff=True)
    
    # Get login activity for this admin user
    login_activities = LoginActivity.objects.filter(user=admin_user).order_by('-created_at')[:10]
    
    # Get notifications sent to this admin user
    notifications = Notification.objects.filter(user=admin_user).order_by('-created_at')[:10]
    
    # Get messages for this admin user
    try:
        messages_received = MessageRecipient.objects.filter(user=admin_user).order_by('-message__created_at')[:10]
    except:
        messages_received = []
    
    # Get basic stats
    total_logins = LoginActivity.objects.filter(user=admin_user).count()
    recent_logins = LoginActivity.objects.filter(
        user=admin_user,
        created_at__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    # Get groups this admin belongs to
    user_groups = admin_user.groups.all()
    
    # Check if admin has special permissions
    is_superuser = admin_user.is_superuser
    
    context = {
        "admin_user": admin_user,
        "login_activities": login_activities,
        "notifications": notifications,
        "messages_received": messages_received,
        "total_logins": total_logins,
        "recent_logins": recent_logins,
        "user_groups": user_groups,
        "is_superuser": is_superuser,
    }
    
    return render(request, "accounts/admin_detail.html", context)


@staff_member_required
def sponsor_fee_ratio(request, user_id):
    """Admin view to change the fee ratio (points per USD) for a sponsor."""
    User = get_user_model()
    sponsor_user = get_object_or_404(User, pk=user_id, groups__name="sponsor")
    
    # Get or create sponsor profile
    sponsor_profile, created = SponsorProfile.objects.get_or_create(user=sponsor_user)
    
    # Get global default for display
    from shop.models import PointsConfig
    global_default = PointsConfig.get_solo().points_per_usd
    
    if request.method == "POST":
        form = SponsorFeeRatioForm(request.POST, instance=sponsor_profile)
        if form.is_valid():
            form.save()
            ratio_display = sponsor_profile.points_per_usd if sponsor_profile.points_per_usd else f"Global default ({global_default})"
            messages.success(
                request,
                f"Fee ratio updated for {sponsor_user.username}. Points per USD: {ratio_display}"
            )
            return redirect("accounts:sponsor_fee_ratio", user_id=user_id)
    else:
        form = SponsorFeeRatioForm(instance=sponsor_profile)
    
    context = {
        "sponsor_user": sponsor_user,
        "sponsor_profile": sponsor_profile,
        "form": form,
        "global_default": global_default,
        "current_ratio": sponsor_profile.points_per_usd or global_default,
    }
    
    return render(request, "accounts/sponsor_fee_ratio.html", context)


@staff_member_required
@require_POST
def archive_sponsor(request, user_id):
    """Archive a sponsor user."""
    from .models import SponsorProfile
    User = get_user_model()
    sponsor_user = get_object_or_404(User, pk=user_id, groups__name="sponsor")
    
    # Get or create sponsor profile
    sponsor_profile, created = SponsorProfile.objects.get_or_create(user=sponsor_user)
    
    if not sponsor_profile.is_archived:
        sponsor_profile.is_archived = True
        sponsor_profile.archived_at = timezone.now()
        sponsor_profile.archived_by = request.user
        sponsor_profile.save()
        messages.success(request, f"Sponsor '{sponsor_user.username}' has been archived.")
    else:
        messages.info(request, f"Sponsor '{sponsor_user.username}' is already archived.")
    
    return redirect("admin_user_search")


@staff_member_required
@require_POST
def unarchive_sponsor(request, user_id):
    """Unarchive a sponsor user."""
    from .models import SponsorProfile
    User = get_user_model()
    sponsor_user = get_object_or_404(User, pk=user_id, groups__name="sponsor")
    
    try:
        sponsor_profile = sponsor_user.sponsor_profile
        if sponsor_profile.is_archived:
            sponsor_profile.is_archived = False
            sponsor_profile.archived_at = None
            sponsor_profile.archived_by = None
            sponsor_profile.save()
            messages.success(request, f"Sponsor '{sponsor_user.username}' has been unarchived.")
        else:
            messages.info(request, f"Sponsor '{sponsor_user.username}' is not archived.")
    except SponsorProfile.DoesNotExist:
        messages.error(request, f"Sponsor profile not found for '{sponsor_user.username}'.")
    
    return redirect("accounts:archived_sponsors")


@staff_member_required
def archived_sponsors(request):
    """View all archived sponsors."""
    from .models import SponsorProfile
    User = get_user_model()
    
    # Get search query
    q = request.GET.get("q", "").strip()
    
    # Get all archived sponsors
    archived_sponsors_qs = User.objects.filter(
        groups__name="sponsor",
        sponsor_profile__is_archived=True
    )
    
    if q:
        archived_sponsors_qs = archived_sponsors_qs.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q)
        )
    
    archived_sponsors_qs = archived_sponsors_qs.order_by("-sponsor_profile__archived_at")
    
    # Pagination
    page_number = request.GET.get("page", 1)
    paginator = Paginator(archived_sponsors_qs, 25)
    archived_sponsors_page = paginator.get_page(page_number)
    
    context = {
        "archived_sponsors": archived_sponsors_page,
        "q": q,
        "total_archived": archived_sponsors_qs.count(),
    }
    
    return render(request, "accounts/archived_sponsors.html", context)


@login_required
@transaction.atomic
def sponsor_driver_search(request):
    """Sponsor page: list only THIS sponsor’s drivers and allow award/deduct per row."""
    user = request.user
    # gate: sponsors (or superusers) only
    if not (user.is_superuser or user.groups.filter(name="sponsor").exists()):
        messages.error(request, "Access denied.")
        return redirect("accounts:profile")

    sponsor = user  # shorthand

    # ---------- POST: award/deduct ----------
    if request.method == "POST":
        form = SponsorAwardForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid input.")
            return redirect("accounts:sponsor_driver_search")

        driver_id = form.cleaned_data["driver_id"]
        reason    = form.cleaned_data.get("reason", "")
        delta     = form.delta()  # positive for Award, negative for Deduct

        driver = get_object_or_404(User, id=driver_id)

        # --- sponsorship checks ---
        prof = getattr(driver, "driver_profile", None)

        # new M2M relationship
        is_m2m = bool(prof and prof.sponsors.filter(id=sponsor.id).exists())

        # legacy string-based sponsor linkage
        is_legacy = bool(prof and prof.sponsor_name == sponsor.username)

        # approved SponsorshipRequest in either direction
        has_request = SponsorshipRequest.objects.filter(
            status="approved"
        ).filter(
            Q(from_user=sponsor, to_user=driver) |
            Q(from_user=driver, to_user=sponsor)
        ).exists()
        
        if not (is_m2m or is_legacy or has_request):
            messages.error(request, "This driver is not under your sponsorship.")
            return redirect("accounts:sponsor_driver_search")
        
        wallet, _ = SponsorPointsAccount.objects.select_for_update().get_or_create(
            sponsor=sponsor,
            driver=driver,
            defaults={"balance": 0},
        )

        if delta < 0 and wallet.balance < abs(delta):
            messages.error(request, "Insufficient points to deduct that amount.")
            return redirect("accounts:sponsor_driver_search")

        try:
            wallet.apply_points(delta, reason=reason, created_by=user)
        except Exception as e:
            messages.error(request, f"Could not update points: {e}")
        else:
            messages.success(request, "Points updated successfully.")

        return redirect("accounts:sponsor_driver_search")

    # ---------- GET: list this sponsor’s drivers ----------
    q = (request.GET.get("q") or "").strip()

    drivers_qs = (
        User.objects.filter(driver_profile__isnull=False, is_staff=False)
        .filter(
            # sponsor -> driver (sponsor sent the request)
            Q(received_sponsorship_requests__from_user=sponsor,
                received_sponsorship_requests__status="approved")
            |
            # driver -> sponsor (driver sent the request)
            Q(sent_sponsorship_requests__to_user=sponsor,
                sent_sponsorship_requests__status="approved")
        )
        .distinct()
    )
    if q:
        id_query = None
        if q.lower().startswith("id:"):
            tok = q.split(":", 1)[1].strip()
            if tok.isdigit():
                id_query = int(tok)
        elif q.isdigit():
            id_query = int(q)

        filters = (
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(driver_profile__first_name__icontains=q)
            | Q(driver_profile__last_name__icontains=q)
            | Q(driver_profile__phone__icontains=q)
            | Q(driver_profile__address__icontains=q)
        )
        if id_query is not None:
            filters |= Q(pk=id_query)
        
        drivers_qs = drivers_qs.filter(filters)

    # annotate balance from THIS sponsor's wallet
    wallet_subq = SponsorPointsAccount.objects.filter(
        driver=OuterRef("pk"), sponsor=sponsor
    ).values("balance")[:1]
    drivers_qs = drivers_qs.annotate(
        sponsor_balance=Subquery(wallet_subq, output_field=IntegerField())
    ).order_by("username")

    page = request.GET.get("page", 1)
    drivers_page = Paginator(drivers_qs, 25).get_page(page)

    return render(
        request,
        "accounts/sponsor_driver_search.html",
        {"drivers": drivers_page, "q": q, "sponsor": sponsor},
    )

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)
    is_delayed = order_is_delayed(order)
    return render(request, "shop/order_detail.html", {"order": order, "is_delayed": is_delayed})


def landing_url_for(user) -> str:
    """
    Decide where a user should land after login based on role.
    Order matters: Admin > Sponsor > Driver > fallback.
    """
    if user.is_staff or user.is_superuser:
        return reverse("admin_user_search")  # your custom admin landing
    if user.groups.filter(name="sponsor").exists():
        return reverse("accounts:sponsor_driver_search")
    if hasattr(user, "driver_profile"):
        return reverse("accounts:profile")  # or 'accounts:profile_preview'
    # Fallback if the account has no role markers
    return reverse("about")

from django.contrib.auth.views import LoginView

class FrontLoginView(LoginView):
    template_name = "registration/login.html"

    def get(self, request, *args, **kwargs):
        """Check if user is locked out before showing login form."""
        username = request.GET.get('username', '')
        if username and self.is_locked_out(username):
            messages.error(request, "This account is temporarily locked due to too many failed login attempts. Please try again later.")
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """Check lockout before processing login attempt."""
        username = request.POST.get('username', '')
        
        # Check if user is locked out
        if self.is_locked_out(username):
            messages.error(request, "This account is temporarily locked due to too many failed login attempts. Please try again later.")
            return self.form_invalid(self.get_form())
        
        return super().post(request, *args, **kwargs)

    def is_locked_out(self, username):
        """Check if the user is currently locked out based on LockoutPolicy."""
        if not username:
            return False
            
        policy = LockoutPolicy.get_policy()
        
        # If policy is disabled, no lockout
        if not policy.enabled:
            return False
        
        ip_address = self.get_client_ip()
        now = timezone.now()
        
        # Get recent failed attempts (within reset window)
        reset_window = now - timedelta(minutes=policy.reset_attempts_after_minutes)
        recent_attempts = FailedLoginAttempt.objects.filter(
            username=username,
            ip_address=ip_address,
            timestamp__gte=reset_window
        ).order_by('-timestamp')
        
        attempt_count = recent_attempts.count()
        
        # If they've reached max attempts, check if lockout period has passed
        if attempt_count >= policy.max_failed_attempts:
            # Get the attempt that triggered the lockout (the Nth attempt)
            lockout_trigger = recent_attempts[policy.max_failed_attempts - 1]
            lockout_until = lockout_trigger.timestamp + timedelta(minutes=policy.lockout_duration_minutes)
            
            # Still locked out?
            if now < lockout_until:
                return True
        
        return False

    def form_invalid(self, form):
        username = self.request.POST.get("username", "")
        ip_address = self.get_client_ip()
        
        # Record the failed attempt
        FailedLoginAttempt.objects.create(username=username, ip_address=ip_address)
        
        # Check if this attempt triggers a lockout
        policy = LockoutPolicy.get_policy()
        if policy.enabled:
            reset_window = timezone.now() - timedelta(minutes=policy.reset_attempts_after_minutes)
            attempt_count = FailedLoginAttempt.objects.filter(
                username=username,
                ip_address=ip_address,
                timestamp__gte=reset_window
            ).count()
            
            if attempt_count >= policy.max_failed_attempts:
                remaining_attempts = 0
                messages.error(
                    self.request,
                    f"Account locked due to too many failed attempts. Please try again in {policy.lockout_duration_minutes} minutes."
                )
            else:
                remaining_attempts = policy.max_failed_attempts - attempt_count
                if remaining_attempts <= 2:  # Warn when getting close
                    messages.warning(
                        self.request,
                        f"Invalid credentials. {remaining_attempts} attempt(s) remaining before lockout."
                    )
        
        return super().form_invalid(form)

    def get_client_ip(self):
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return self.request.META.get('REMOTE_ADDR')

    def form_valid(self, form):
        # Let Django log them in first 
        # Exception: If TOTP MFA is enabled, we intercept here to require TOTP verification
        # Then override the redirect to be role-aware
        user = form.get_user()
        
        # Clear failed login attempts on successful login
        username = self.request.POST.get("username", "")
        ip_address = self.get_client_ip()
        if username:
            FailedLoginAttempt.objects.filter(
                username=username,
                ip_address=ip_address
            ).delete()

        #pull or create MFA record for this user
        from .models import UserMFA
        mfa_record = UserMFA.for_user(user)

        #if MFA is enabled, redirect to TOTP verification page
        if mfa_record.mfa_enabled and mfa_record.mfa_totp_secret:
            self.request.session["pending_user_id"] = user.id
            self.request.session.set_expiry(300)

            return redirect("accounts:mfa_challenge")
        
        response = super().form_valid(form) #logs user in normally
        return HttpResponseRedirect(landing_url_for(self.request.user))

def is_sponsor(user):
    # TODO: replace with your real sponsor-role check
    return getattr(user, "is_sponsor", False) or user.groups.filter(name="sponsor").exists()

@login_required
@user_passes_test(is_sponsor)
@transaction.atomic
def sponsor_award_points(request):
    if request.method == "POST":
        form = SponsorAwardForm(request.POST)
        if form.is_valid():
            driver = get_object_or_404(User, pk=form.cleaned_data["driver_id"])
            amount = form.cleaned_data["amount"]
            reason = form.cleaned_data.get("reason", "")
            delta = form.delta()
            wallet, _ = SponsorPointsAccount.objects.select_for_update().get_or_create(
                driver=driver, sponsor=request.user, defaults={"balance": 0}
            )

            if delta < 0 and wallet.balance < abs(delta):
                messages.error(request, "Insufficient points to deduct.")
            else:
                wallet.apply_points(delta, reason=reason, awarded_by=request.user)
                if delta > 0:
                    messages.success(request, f"Awarded {amount} points to {driver.username}.")
                else:
                    messages.success(request, f"Deducted {amount} points from {driver.username}.")
            return redirect(reverse("accounts:sponsor_award_points"))
    else:
        form = SponsorAwardForm()
    return render(request, "accounts/sponsor_award_points.html", {"form": form})

@login_required
def wallets(request):
    qs = SponsorPointsAccount.objects.filter(driver=request.user).select_related("sponsor")
    if request.method == "POST":
        form = SetPrimaryWalletForm(request.POST, driver=request.user)
        if form.is_valid():
            wallet = form.cleaned_data["wallet_id"]
            wallet.set_primary()
            messages.success(request, "Primary sponsor wallet updated.")
            return redirect("accounts:wallets")
    else:
        form = SetPrimaryWalletForm(driver=request.user)
    return render(request, "accounts/wallets.html", {"wallets": qs, "form": form})

@staff_member_required
def messages_compose(request):
    if request.method == "POST":
        form = MessageComposeForm(request.POST)
        if form.is_valid():
            msg = form.save(commit = False)
            msg.author = request.user
            msg.save()
            form.save_m2m()  # for direct_users

            # Determine recipients
            recipients = User.objects.none()
            active = User.objects.filter(is_active=True)

            data = form.cleaned_data
            if data["select_all"]:
                recipients = active
            else:
                if data["include_admins"]:
                    recipients = recipients | active.filter(Q(is_staff=True) | Q(is_superuser=True))
                if data["include_sponsors"]:
                    recipients = recipients | active.filter(groups__name="sponsor")
                if data["include_drivers"]:
                    recipients = (
                        recipients | active.filter(driver_profile__isnull=False)
                        .exclude(groups__name="sponsor")
                        .exclude(Q(is_staff=True) | Q(is_superuser=True))
                    )
                if data["users"]:
                    recipients = recipients | data["users"] 
            recipients = recipients.distinct()

            MessageRecipient.objects.bulk_create(
                [MessageRecipient(message=msg, user=u) for u in recipients],
                ignore_conflicts = True,
            )

            messages.success(request, f"Message sent to {recipients.count()} recipients.")
            return redirect("accounts:messages_sent")
    else:
        form = MessageComposeForm()
    return render(request, "accounts/messages_compose.html", {"form": form})

@login_required
def messages_inbox(request):
    rows = (MessageRecipient.objects
            .select_related("message", "message__author")
            .filter(user=request.user)
            .order_by("delivered_at")
    )
    return render(request, "accounts/messages_inbox.html", {"rows": rows})

@staff_member_required
def messages_sent(request):
    rows = Message.objects.filter(author = request.user).order_by("-created_at")
    return render(request, "accounts/messages_sent.html", {"rows": rows})

@login_required
@require_POST
def message_delete(request, pk: int):
    item = get_object_or_404(MessageRecipient, pk=pk, user=request.user)
    item.delete()
    messages.success(request, "Message deleted.")
    return redirect(request.META.get("HTTP_REFERER", "accounts:messages_inbox"))

@login_required
@require_POST
def messages_bulk_delete(request):
    ids = request.POST.getlist("ids")
    if ids:
        (MessageRecipient.objects
            .filter(user=request.user, pk__in=ids)
            .delete())
        messages.success(request, "Selected messages deleted.")
    else:
        messages.info(request, "No messages selected for deletion.")
    return redirect("accounts:messages_inbox")

@staff_member_required
@require_POST
def message_sent_delete(request, pk: int):
    msg = get_object_or_404(Message, pk=pk, author=request.user)
    msg.delete()
    messages.success(request, "Sent message deleted.")
    return redirect("accounts:messages_sent")

@staff_member_required
def login_activity(request):
    """Admin page: list login activity records with optional user filter and success/failure filter."""
    qs = LoginActivity.objects.select_related("user").all()
    user_q = request.GET.get("user", "").strip()
    status = request.GET.get("status", "")  # 'success' | 'fail' | ''

    if user_q:
        # allow searching by username or id
        if user_q.isdigit():
            qs = qs.filter(models.Q(user__id=int(user_q)) | models.Q(username__icontains=user_q))
        else:
            qs = qs.filter(models.Q(user__username__icontains=user_q) | models.Q(username__icontains=user_q))

    if status == "success":
        qs = qs.filter(successful=True)
    elif status == "fail":
        qs = qs.filter(successful=False)

    qs = qs.order_by("-created_at")

    paginator = Paginator(qs, 50)
    page = request.GET.get("page", 1)
    page_obj = paginator.get_page(page)

    return render(request, "accounts/login_activity.html", {"page": page_obj, "user_q": user_q, "status": status})

@login_required
def message_detail(request, pk: int):
    item = get_object_or_404(MessageRecipient.objects.select_related("message", "message__author"), 
                            pk=pk, user=request.user)
    if not item.is_read:
        item.is_read = True
        item.read_at = timezone.now()
        item.save(update_fields = ["is_read", "read_at"])
    return render(request, "accounts/messages_detail.html", {"item":item})

@staff_member_required
def create_driver(request):
    """Admin-only page to create a new driver user with DriverProfile."""
    User = get_user_model()

    class DriverCreateForm(forms.Form):
        username = forms.CharField(max_length=150)
        email = forms.EmailField(required=False)
        password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
        password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")
        phone = forms.CharField(max_length=20, required=False)
        address = forms.CharField(max_length=255, required=False)

        def clean_username(self):
            u = self.cleaned_data["username"]
            if User.objects.filter(username=u).exists():
                raise forms.ValidationError("Username already exists")
            return u

        def clean(self):
            cleaned = super().clean()
            p1 = cleaned.get("password1")
            p2 = cleaned.get("password2")
            if p1 and p2 and p1 != p2:
                raise forms.ValidationError("Passwords do not match")
            return cleaned

    if request.method == "POST":
        form = DriverCreateForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            email = form.cleaned_data.get("email", "")
            password = form.cleaned_data["password1"]
            phone = form.cleaned_data.get("phone", "")
            address = form.cleaned_data.get("address", "")

            user = User.objects.create_user(username=username, email=email, password=password)
            # ensure not staff
            user.is_staff = False
            user.is_superuser = False
            user.save()
            # create driver profile
            from .models import DriverProfile
            DriverProfile.objects.create(user=user, phone=phone, address=address)

            messages.success(request, f"Driver '{username}' created.")
            return redirect("admin_user_search")
    else:
        form = DriverCreateForm()

    return render(request, "accounts/create_driver.html", {"form": form})


@staff_member_required
def create_sponsor(request):
    """Admin-only page to create a new sponsor user (added to 'sponsor' group)."""
    User = get_user_model()

    class SponsorCreateForm(forms.Form):
        username = forms.CharField(max_length=150)
        email = forms.EmailField(required=False)
        password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
        password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")

        def clean_username(self):
            u = self.cleaned_data["username"]
            if User.objects.filter(username=u).exists():
                raise forms.ValidationError("Username already exists")
            return u

        def clean(self):
            cleaned = super().clean()
            p1 = cleaned.get("password1")
            p2 = cleaned.get("password2")
            if p1 and p2 and p1 != p2:
                raise forms.ValidationError("Passwords do not match")
            return cleaned

    if request.method == "POST":
        form = SponsorCreateForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            email = form.cleaned_data.get("email", "")
            password = form.cleaned_data["password1"]

            user = User.objects.create_user(username=username, email=email, password=password)
            # ensure not staff
            user.is_staff = False
            user.is_superuser = False
            user.save()
            # add to sponsor group (create group if missing)
            from django.contrib.auth.models import Group
            from .models import SponsorProfile
            sponsor_group, _ = Group.objects.get_or_create(name="sponsor")
            user.groups.add(sponsor_group)
            
            # Create sponsor profile
            SponsorProfile.objects.get_or_create(user=user)

            messages.success(request, f"Sponsor '{username}' created.")
            return redirect("admin_user_search")
    else:
        form = SponsorCreateForm()

    return render(request, "accounts/create_sponsor.html", {"form": form})

@staff_member_required
def bulk_upload_users(request):
    """
    Admin-only view to bulk upload users (drivers or sponsors) from a CSV file.
    CSV format:
    username,email,password,user_type,phone,address,sponsor_name,sponsor_email
    """
    upload_log = None
    results = None
    
    if request.method == "POST":
        csv_file = request.FILES.get("file")
        if not csv_file or not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a valid .csv file.")
            return render(request, "accounts/bulk_upload.html", {
                "upload_log": upload_log,
                "results": results,
            })

        file_data = TextIOWrapper(csv_file.file, encoding="utf-8")
        reader = csv.DictReader(file_data)

        created_count = 0
        skipped_count = 0
        error_count = 0
        errors = []
        created_users = []
        skipped_users = []
        total_rows = 0

        with transaction.atomic():
            for row in reader:
                total_rows += 1
                username = row.get("username", "").strip()
                email = row.get("email", "").strip()
                password = row.get("password", "").strip()
                user_type = row.get("user_type", "").strip().lower()

                if not username or not password or not email or user_type not in ["driver", "sponsor"]:
                    skipped_count += 1
                    error_count += 1
                    error_msg = f"Row {total_rows}: Invalid data for user {username or '(missing username)'} - missing required fields or invalid user_type"
                    errors.append(error_msg)
                    skipped_users.append(username or f"Row {total_rows}")
                    continue

                # Skip duplicates
                if User.objects.filter(username=username).exists():
                    skipped_count += 1
                    error_msg = f"Row {total_rows}: User '{username}' already exists"
                    errors.append(error_msg)
                    skipped_users.append(username)
                    continue

                try:
                    # Create user
                    user = User.objects.create_user(username=username, email=email, password=password)
                    user.is_active = True
                    user.save()

                    # Handle driver creation
                    if user_type == "driver":
                        phone = row.get("phone", "").strip()
                        address = row.get("address", "").strip()
                        DriverProfile.objects.create(user=user, phone=phone, address=address)

                    # Handle sponsor group
                    elif user_type == "sponsor":
                        sponsor_group, _ = Group.objects.get_or_create(name="sponsor")
                        user.groups.add(sponsor_group)

                    created_count += 1
                    created_users.append(username)
                except Exception as e:
                    skipped_count += 1
                    error_count += 1
                    error_msg = f"Row {total_rows}: Error creating user '{username}': {str(e)}"
                    errors.append(error_msg)
                    skipped_users.append(username)

            # Create upload log
            upload_log = BulkUploadLog.objects.create(
                uploaded_by=request.user,
                filename=csv_file.name,
                total_rows=total_rows,
                created_count=created_count,
                skipped_count=skipped_count,
                error_count=error_count,
                errors=errors,
                created_users=created_users,
                skipped_users=skipped_users,
            )

        # Prepare results for display
        results = {
            "total_rows": total_rows,
            "created_count": created_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "success_rate": round((created_count / total_rows * 100), 1) if total_rows > 0 else 0,
            "errors": errors[:20],  # Show first 20 errors
            "created_users": created_users[:50],  # Show first 50 created users
            "skipped_users": skipped_users[:50],  # Show first 50 skipped users
            "has_more_errors": len(errors) > 20,
            "has_more_created": len(created_users) > 50,
            "has_more_skipped": len(skipped_users) > 50,
        }

        if created_count > 0:
            messages.success(request, f"✅ Successfully created {created_count} user(s)!")
        if skipped_count > 0:
            messages.warning(request, f"⚠️ {skipped_count} row(s) were skipped. See details below.")

    # Get recent upload history
    recent_uploads = BulkUploadLog.objects.all()[:10]
    
    return render(request, "accounts/bulk_upload.html", {
        "upload_log": upload_log,
        "results": results,
        "recent_uploads": recent_uploads,
    })


@staff_member_required
def bulk_upload_history(request):
    """View upload history and details of past uploads."""
    uploads = BulkUploadLog.objects.all().order_by("-created_at")
    
    # Pagination
    paginator = Paginator(uploads, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    
    return render(request, "accounts/bulk_upload_history.html", {
        "page_obj": page_obj,
    })


@staff_member_required
def bulk_upload_detail(request, upload_id):
    """View detailed results of a specific upload."""
    upload_log = get_object_or_404(BulkUploadLog, id=upload_id)
    
    return render(request, "accounts/bulk_upload_detail.html", {
        "upload_log": upload_log,
    })


@staff_member_required
def toggle_user_active(request, user_id):
    """Toggle the is_active flag for a user (deactivate/reactivate). Staff-only POST endpoint."""
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("admin_user_search")

    user = get_object_or_404(User, id=user_id)
    # prevent staff from accidentally deactivating themselves
    if user == request.user:
        messages.error(request, "You cannot change your own active status.")
        return redirect("admin_user_search")

    user.is_active = not user.is_active
    user.save()
    action = "reactivated" if user.is_active else "deactivated"
    messages.success(request, f"User '{user.username}' has been {action}.")
    return redirect(request.META.get("HTTP_REFERER", "admin_user_search"))

@staff_member_required
def toggle_lock_user(request, user_id):
    """
    Admin-only action: toggles a driver's locked status.
    Locked users cannot log in or access protected pages.
    """
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("admin_user_search")

    user = get_object_or_404(User, id=user_id)
    profile = getattr(user, "driver_profile", None)

    if not profile:
        messages.error(request, "This user does not have a driver profile.")
        return redirect("admin_user_search")

    profile.is_locked = not profile.is_locked
    profile.save()

    action = "locked" if profile.is_locked else "unlocked"
    messages.success(request, f"Driver '{user.username}' has been {action}.")
    return redirect(request.META.get("HTTP_REFERER", "admin_user_search"))

@staff_member_required
@require_POST
def toggle_suspend_user(request, user_id):
    """Suspend or unsuspend a user account."""
    user = get_object_or_404(User, id=user_id)
    profile = getattr(user, "driver_profile", None)

    if not profile:
        messages.error(request, "User does not have a driver profile.")
        return redirect("admin_user_search")

    profile.is_suspended = not profile.is_suspended
    profile.save()

    status = "unsuspended" if not profile.is_suspended else "suspended"
    messages.success(request, f"User '{user.username}' has been {status}.")
    return redirect(request.META.get("HTTP_REFERER", "admin_user_search"))

@staff_member_required
def force_logout_user(request, user_id):
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("admin_user_search")

    if user_id == request.user.id:
        messages.error(request, "You cannot log yourself out.")
        return redirect("admin_user_search")

    # Loop through all sessions and delete those belonging to the user
    user_model = get_user_model()
    user = get_object_or_404(user_model, pk=user_id)

    sessions = Session.objects.all()
    count = 0
    for session in sessions:
        data = session.get_decoded()
        if str(user.pk) == str(data.get('_auth_user_id')):
            session.delete()
            count += 1

    messages.success(request, f"User '{user.username}' was logged out from {count} active session(s).")
    return redirect(request.META.get("HTTP_REFERER", "admin_user_search"))

class NotificationPrefsForm(forms.ModelForm):
    class Meta:
        model = DriverNotificationPreference
        fields = ["orders", "points", "promotions"]
        widgets = {
            "orders": forms.CheckboxInput(),
            "points": forms.CheckboxInput(),
            "promotions": forms.CheckboxInput(),
        }
########################################################
@login_required
def notifications(request):
    rows = (Notification.objects
        .filter(user=request.user)
        .order_by("-created_at"))
    return render(request, "accounts/notifications.html", {"rows": rows})

@login_required
def notification_settings(request):
    prefs = DriverNotificationPreference.for_user(request.user)

    if request.method == "POST":
        form = NotificationPreferenceForm(request.POST, request.FILES, instance=prefs)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification settings saved.")
            return redirect("accounts:notification_settings")
    else:
        form = NotificationPreferenceForm(instance=prefs)

    # Resolve a preview URL for the test button
    preview_url = ""
    if prefs.sound_mode == "default":
        preview_url = static("sounds/default-chime.mp3") 
    elif prefs.sound_mode == "custom" and prefs.sound_file:
        preview_url = prefs.sound_file.url  

    return render(
        request,
        "accounts/notification_settings.html",
        {"form": form, "preview_url": preview_url, "prefs": prefs},
    )

@login_required
@require_POST
def notifications_clear(request):
    Notification.objects.filter(user=request.user).delete()
    MessageRecipient.objects.filter(user=request.user).delete()
    messages.success(request, "All notifications & messages cleared.")
    return redirect("accounts:notifications_feed")

@login_required
@require_POST
def notification_delete(request, pk: int):
    notif = get_object_or_404(Notification, pk=pk, user=request.user)
    notif.delete()
    messages.success(request, "Notification deleted.")
    return redirect(request.META.get("HTTP_REFERER", "accounts:notifications"))

@login_required
@require_POST
def notifications_bulk_delete(request):
    ids = request.POST.getlist("ids")
    if ids:
        Notification.objects.filter(user=request.user, pk__in=ids).delete()
        messages.success(request, "Selected notifications deleted.")
    else:
        messages.info(request, "No notifications selected for deletion.")
    return redirect("accounts:notifications")

@login_required
def notifications_feed(request):
    rows = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(request, "accounts/notifications_feed.html", {"rows": rows})


@login_required
def notifications_history(request):
    """
    Dashboard list of all notifications with search, filters, pagination.
    Groups by day in the template via the annotated 'day' field.
    """
    qs = Notification.objects.filter(user=request.user)

    # filters
    kind = request.GET.get("kind", "")
    if kind:
        qs = qs.filter(kind=kind)

    read = request.GET.get("read", "")
    if read == "unread":
        qs = qs.filter(read=False)
    elif read == "read":
        qs = qs.filter(read=True)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))

    # Apply annotation and ordering after filters
    qs = qs.annotate(day=TruncDate("created_at")).order_by("-created_at")

    paginator = Paginator(qs, 15)  
    page_obj = paginator.get_page(request.GET.get("page"))
    
    # Convert to list to ensure annotation is evaluated
    notifications_list = list(page_obj.object_list)

    context = {
        "page_obj": page_obj,
        "notifications_list": notifications_list,  # Pass as list for template
        "q": q,
        "read": read,
        "kind": kind,
        "kind_choices": Notification.KIND_CHOICES,
    }
    return render(request, "accounts/notification_history.html", context)


@login_required
def points_history(request):
    # Only allow drivers (not sponsors or admins)
    is_driver = hasattr(request.user, "driver_profile")
    is_sponsor = request.user.groups.filter(name="sponsor").exists()
    is_admin = request.user.is_staff or request.user.is_superuser
    
    if not is_driver or is_sponsor or is_admin:
        messages.error(request, "Points history is only available to drivers.")
        return redirect("accounts:profile")
    
    rows = PointsLedger.objects.filter(user=request.user).order_by("-created_at")
    balance = rows.aggregate(s=Sum("delta"))["s"] or 0
    return render(request, "accounts/points_history.html", {"rows": rows, "balance": balance})

@login_required
def points_history_download(request):
    """Download points history as CSV or PDF."""
    # Only allow drivers (not sponsors or admins)
    is_driver = hasattr(request.user, "driver_profile")
    is_sponsor = request.user.groups.filter(name="sponsor").exists()
    is_admin = request.user.is_staff or request.user.is_superuser
    
    if not is_driver or is_sponsor or is_admin:
        return HttpResponse("Points history download is only available to drivers.", status=403)
    
    format_type = request.GET.get("format", "csv").lower()
    rows = PointsLedger.objects.filter(user=request.user).order_by("-created_at")
    balance = rows.aggregate(s=Sum("delta"))["s"] or 0
    
    if format_type == "csv":
        # Generate CSV
        response = HttpResponse(content_type="text/csv")
        filename = f"points_history_{request.user.username}_{timezone.now().strftime('%Y%m%d')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        
        writer = csv.writer(response)
        writer.writerow(["Date", "Change", "Reason", "Balance After"])
        
        for row in rows:
            writer.writerow([
                row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                f"{'+' if row.delta >= 0 else ''}{row.delta}",
                row.reason or "",
                row.balance_after,
            ])
        
        # Add summary row
        writer.writerow([])
        writer.writerow(["Total Balance", "", "", balance])
        
        return response
    
    elif format_type == "pdf" and PDF_AVAILABLE:
        # Generate PDF
        html = render_to_string(
            "accounts/points_history_pdf.html",
            {
                "rows": rows,
                "balance": balance,
                "user": request.user,
                "generated_at": timezone.now(),
            },
        )
        
        pdf_io = BytesIO()
        result = pisa.CreatePDF(src=html, dest=pdf_io, encoding="UTF-8")
        
        if result.err:
            return HttpResponse("Error generating PDF", status=500)
        
        pdf = pdf_io.getvalue()
        filename = f"points_history_{request.user.username}_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    
    elif format_type == "pdf" and not PDF_AVAILABLE:
        return HttpResponse("PDF generation is not available. Please use CSV format.", status=400)
    
    else:
        return HttpResponse("Invalid format. Use 'csv' or 'pdf'.", status=400)

@login_required
def points_goal_tracker(request):
    """Points goal tracker with progress bar for drivers."""
    # Only allow drivers (not sponsors or admins)
    is_driver = hasattr(request.user, "driver_profile")
    is_sponsor = request.user.groups.filter(name="sponsor").exists()
    is_admin = request.user.is_staff or request.user.is_superuser
    
    if not is_driver or is_sponsor or is_admin:
        messages.error(request, "Points goal tracker is only available to drivers.")
        return redirect("accounts:profile")
    
    profile, _ = DriverProfile.objects.get_or_create(user=request.user)
    current_balance = get_driver_points_balance(request.user)
    
    # Calculate progress
    progress_percentage = 0
    points_remaining = 0
    if profile.points_goal and profile.points_goal > 0:
        progress_percentage = min(100, int((current_balance / profile.points_goal) * 100))
        points_remaining = max(0, profile.points_goal - current_balance)
    
    # Handle form submission
    if request.method == "POST":
        form = PointsGoalForm(request.POST)
        if form.is_valid():
            profile.points_goal = form.cleaned_data["points_goal"]
            profile.save()
            messages.success(request, f"Points goal updated to {profile.points_goal} points!")
            return redirect("accounts:points_goal_tracker")
    else:
        form = PointsGoalForm(initial={"points_goal": profile.points_goal or 0})
    
    context = {
        "form": form,
        "current_balance": current_balance,
        "points_goal": profile.points_goal,
        "progress_percentage": progress_percentage,
        "points_remaining": points_remaining,
        "has_goal": bool(profile.points_goal),
    }
    
    return render(request, "accounts/points_goal_tracker.html", context)


@login_required
def contact_sponsor(request):
    profile = getattr(request.user, "driver_profile", None)

    if not profile:
        return render(request, "accounts/contact_sponsor.html", {
            "error": "No sponsor contact information available.",
        })

    # Get all sponsors for this driver
    driver_sponsors = list(profile.sponsors.all())
    
    # Also check legacy sponsor_name field
    if profile.sponsor_name:
        try:
            legacy_sponsor = User.objects.filter(
                username=profile.sponsor_name,
                groups__name="sponsor"
            ).first()
            if legacy_sponsor and legacy_sponsor not in driver_sponsors:
                driver_sponsors.append(legacy_sponsor)
        except Exception:
            pass

    # If no sponsors, show error
    if not driver_sponsors:
        return render(request, "accounts/contact_sponsor.html", {
            "error": "No sponsor contact information available.",
            "form": ContactSponsorForm(),
            "driver_sponsors": [],
        })

    # Get selected sponsor from request (POST or GET)
    selected_sponsor_id = request.POST.get("sponsor_id") or request.GET.get("sponsor_id", "").strip()
    sponsor_user = None
    
    if selected_sponsor_id:
        try:
            sponsor_user = next((s for s in driver_sponsors if str(s.id) == selected_sponsor_id), None)
        except (ValueError, TypeError):
            pass
    
    # If no sponsor selected or invalid, use first sponsor
    if not sponsor_user and driver_sponsors:
        sponsor_user = driver_sponsors[0]
    
    sponsor_name = sponsor_user.get_full_name() or sponsor_user.username if sponsor_user else None

    # Handle form submission
    if request.method == "POST":
        form = ContactSponsorForm(request.POST)
        if form.is_valid():
            subject = form.cleaned_data["subject"]
            message_body = form.cleaned_data["message"]
            
            # Create a notification for the sponsor
            from .notifications import send_in_app_notification
            from django.urls import reverse
            
            try:
                # Create notification with a link to messages
                messages_url = reverse("accounts:messages_inbox")
                notification_body = f"Message from {request.user.get_full_name() or request.user.username}:\n\n{message_body}"
                
                send_in_app_notification(
                    sponsor_user,
                    "dropped",  # Use "dropped" kind so it can't be muted
                    f"Message from Driver: {subject}",
                    notification_body,
                    url=messages_url,
                )
                
                # Also create a Message/MessageRecipient for the inbox
                from .models import Message, MessageRecipient
                msg = Message.objects.create(
                    author=request.user,
                    subject=f"Driver Message: {subject}",
                    body=message_body,
                )
                MessageRecipient.objects.create(
                    message=msg,
                    user=sponsor_user,
                )
                
                messages.success(request, f"Message sent to {sponsor_name}!")
                return redirect(f"{reverse('accounts:contact_sponsor')}?sponsor_id={sponsor_user.id}")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to send message to sponsor: {e}", exc_info=True)
                messages.error(request, "Failed to send message. Please try again.")
    else:
        form = ContactSponsorForm()

    # Pass data to the template
    return render(request, "accounts/contact_sponsor.html", {
        "form": form,
        "sponsor_name": sponsor_name or "Your Sponsor",
        "sponsor_user": sponsor_user,
        "driver_sponsors": driver_sponsors,
        "selected_sponsor_id": str(sponsor_user.id) if sponsor_user else "",
    })


@login_required
def my_sponsor(request):
    """Display sponsor contact information for drivers."""
    # Check if user is a driver (has driver_profile and not in sponsor group)
    profile = getattr(request.user, "driver_profile", None)
    
    if not profile:
        messages.error(request, "This page is only available to drivers.")
        return redirect("accounts:profile")
    
    # Check if user is a sponsor
    if request.user.groups.filter(name="sponsor").exists():
        messages.error(request, "This page is only available to drivers.")
        return redirect("accounts:profile")
    
    # Get sponsor information from driver profile
    sponsor_name = profile.sponsor_name or None
    sponsor_email = profile.sponsor_email or None
    
    # Try to find the actual sponsor user if sponsor_name is set
    sponsor_user = None
    if sponsor_name:
        try:
            sponsor_user = User.objects.filter(
                username=sponsor_name,
                groups__name="sponsor"
            ).first()
        except User.DoesNotExist:
            pass
    
    context = {
        "driver_profile": profile,
        "sponsor_name": sponsor_name,
        "sponsor_email": sponsor_email,
        "sponsor_user": sponsor_user,
        "has_sponsor": bool(sponsor_name or sponsor_email),
    }
    
    return render(request, "accounts/my_sponsor.html", context)


@staff_member_required
def admin_active_sessions(request):
    sort = request.GET.get("sort", "recent")
    sessions = []
    for session in Session.objects.all():
        data = session.get_decoded()
        user_id = data.get('_auth_user_id')
        if user_id:
            try:
                user = User.objects.get(id=user_id)
                sessions.append({
                    "user": user,
                    "session_key": session.session_key,
                    "ip": data.get("ip_address", "N/A"),  
                    "last_activity": localtime(session.expire_date),
                })
            except User.DoesNotExist:
                pass

    reverse = sort != "oldest"
    sessions.sort(key=lambda s: s["last_activity"], reverse=reverse)

    return render(request, "accounts/admin_active_sessions.html", {
        "sessions": sessions,
        "sort": sort,
    })

@staff_member_required
@require_POST
def terminate_session(request, session_key):
    try:
        session = Session.objects.get(session_key=session_key)
        session.delete()
        messages.success(request, f"Session {session_key} terminated.")
    except Session.DoesNotExist:
        messages.error(request, f"Session {session_key} not found.")
    return redirect("accounts:admin_active_sessions")

def about(request):
    connected = False
    db_name = db_user = db_version = None
    error = None

    try:
        with connections["default"].cursor() as cur:
            # simple ping + some info
            cur.execute("SELECT DATABASE(), USER(), VERSION()")
            db_name, db_user, db_version = cur.fetchone()
        connected = True
    except Exception as e:
        error = str(e)

    # mask DB user for public display (e.g., CP****)
    masked_user = None
    if db_user:
        user_part = db_user.split("@", 1)[0]
        masked_user = (user_part[:2] + "****") if user_part else "****"

    return render(request, "about.html", {
        "connected": connected,
        "db_name": db_name,
        "db_user_masked": masked_user,
        "db_version": db_version,
        "error": error,
        "now": timezone.now(),
    })


def faqs(request):
    """Simple FAQs page."""
    return render(request, "faqs.html")

def api_driver_suggest(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse([], safe=False)
    qs = (User.objects
          .filter(Q(username__icontains=q) |
                  Q(email__icontains=q) |
                  Q(driver_profile__phone__icontains=q) |
                  Q(driver_profile__address__icontains=q))
          .order_by("username")[:12])
    data = [{
        "label": u.username,
        "value": u.username,             # what goes into the input on select
        "hint":  f"{u.email or '—'}"
    } for u in qs]
    return JsonResponse(data, safe=False)

def api_sponsor_suggest(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse([], safe=False)

    if HAS_SPONSOR_MODEL:
        qs = (Sponsor.objects
              .filter(Q(name__icontains=q) | Q(email__icontains=q))
              .order_by("name")[:12])
        data = [{
            "label": getattr(s, "name", str(s)),
            "value": getattr(s, "name", str(s)),
            "hint":  getattr(s, "email", "") or "—",
        } for s in qs]
        return JsonResponse(data, safe=False)
    else:
        # Fallback: suggest USERS in the 'sponsor' group
        from django.contrib.auth.models import Group
        g = Group.objects.filter(name__iexact="sponsor").first()
        user_qs = User.objects.none()
        if g:
            user_qs = (
                User.objects.filter(groups=g)
                .filter(Q(username__icontains=q) | Q(email__icontains=q))
                .order_by("username")[:12]
            )
        data = [{
            "label": u.username,
            "value": u.username,
            "hint":  u.email or "—",
        } for u in user_qs]
        return JsonResponse(data, safe=False)


# --- Support Tickets ---
class SupportTicketForm(forms.Form):
    subject = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"placeholder": "Brief summary of your issue"}))
    description = forms.CharField(widget=forms.Textarea(attrs={"placeholder": "Please describe your issue in detail", "rows": 6}))


@login_required
def submit_ticket(request):
    """Driver-only page to submit a support ticket."""
    if request.method == "POST":
        form = SupportTicketForm(request.POST)
        if form.is_valid():
            from .models import SupportTicket
            ticket = SupportTicket.objects.create(
                driver=request.user,
                subject=form.cleaned_data["subject"],
                description=form.cleaned_data["description"],
                status="open"
            )
            messages.success(request, f"Support ticket #{ticket.id} submitted. You will be notified when it is resolved.")
            return redirect("accounts:submit_ticket")
    else:
        form = SupportTicketForm()
    
    # Show user's existing tickets
    from .models import SupportTicket
    user_tickets = SupportTicket.objects.filter(driver=request.user).order_by("-created_at")
    
    return render(request, "accounts/submit_ticket.html", {"form": form, "user_tickets": user_tickets})


@staff_member_required
def admin_tickets(request):
    """Admin page to view and resolve support tickets."""
    from .models import SupportTicket
    
    status_filter = request.GET.get("status", "open")
    tickets_qs = SupportTicket.objects.select_related("driver", "resolved_by").all()
    
    if status_filter == "open":
        tickets_qs = tickets_qs.filter(status="open")
    elif status_filter == "resolved":
        tickets_qs = tickets_qs.filter(status="resolved")
    
    tickets_qs = tickets_qs.order_by("-created_at")
    
    paginator = Paginator(tickets_qs, 25)
    page_number = request.GET.get("page", 1)
    tickets_page = paginator.get_page(page_number)
    
    return render(request, "accounts/admin_tickets.html", {"tickets": tickets_page, "status_filter": status_filter})


@staff_member_required
@require_POST
def resolve_ticket(request, ticket_id):
    """Admin action to resolve a support ticket and notify the driver."""
    from .models import SupportTicket, Notification
    
    ticket = get_object_or_404(SupportTicket, id=ticket_id)
    ticket.status = "resolved"
    ticket.resolved_at = timezone.now()
    ticket.resolved_by = request.user
    ticket.save()
    
    # Create notification for the driver
    Notification.objects.create(
        user=ticket.driver,
        kind="promotions",  # or create a new kind like "support"
        title=f"Support Ticket #{ticket.id} Resolved",
        body=f"Your support ticket '{ticket.subject}' has been resolved by our team.",
        url=""
    )
    
    messages.success(request, f"Ticket #{ticket.id} marked as resolved and driver notified.")
    return redirect(request.META.get("HTTP_REFERER", "accounts:admin_tickets"))


# --- Complaints ---
class ComplaintForm(forms.Form):
    subject = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"placeholder": "Brief summary of your complaint"}))
    description = forms.CharField(widget=forms.Textarea(attrs={"placeholder": "Please describe your complaint in detail", "rows": 6}))


@login_required
def submit_complaint(request):
    """Driver-only page to submit a complaint."""
    if request.method == "POST":
        form = ComplaintForm(request.POST)
        if form.is_valid():
            from .models import Complaint
            complaint = Complaint.objects.create(
                driver=request.user,
                subject=form.cleaned_data["subject"],
                description=form.cleaned_data["description"],
                status="open"
            )
            messages.success(request, f"Complaint #{complaint.id} submitted. You will be notified when it is resolved.")
            return redirect("accounts:submit_complaint")
    else:
        form = ComplaintForm()
    
    # Show user's existing complaints
    from .models import Complaint
    user_complaints = Complaint.objects.filter(driver=request.user).order_by("-created_at")
    
    return render(request, "accounts/submit_complaint.html", {"form": form, "user_complaints": user_complaints})


@staff_member_required
def admin_complaints(request):
    """Admin page to view and resolve complaints."""
    from .models import Complaint
    
    status_filter = request.GET.get("status", "open")
    complaints_qs = Complaint.objects.select_related("driver", "resolved_by").all()
    
    if status_filter == "open":
        complaints_qs = complaints_qs.filter(status="open")
    elif status_filter == "resolved":
        complaints_qs = complaints_qs.filter(status="resolved")
    
    complaints_qs = complaints_qs.order_by("-created_at")
    
    paginator = Paginator(complaints_qs, 25)
    page_number = request.GET.get("page", 1)
    complaints_page = paginator.get_page(page_number)
    
    return render(request, "accounts/admin_complaints.html", {"complaints": complaints_page, "status_filter": status_filter})


@staff_member_required
@require_POST
def resolve_complaint(request, complaint_id):
    """Admin action to resolve a complaint and notify the driver."""
    from .models import Complaint, Notification
    
    complaint = get_object_or_404(Complaint, id=complaint_id)
    complaint.status = "resolved"
    complaint.resolved_at = timezone.now()
    complaint.resolved_by = request.user
    complaint.save()
    
    # Create notification for the driver
    Notification.objects.create(
        user=complaint.driver,
        kind="promotions",  # or create a new kind like "complaints"
        title=f"Complaint #{complaint.id} Resolved",
        body=f"Your complaint '{complaint.subject}' has been resolved by our team.",
        url=""
    )
    
    messages.success(request, f"Complaint #{complaint.id} marked as resolved and driver notified.")
    return redirect(request.META.get("HTTP_REFERER", "accounts:admin_complaints"))


@staff_member_required
def view_as_driver(request, user_id):
    """
    Admin impersonation feature - allows staff to view the site as a specific driver.
    Stores the original admin user ID in session for troubleshooting and audit purposes.
    """
    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    
    # Prevent impersonating other staff members
    if target_user.is_staff or target_user.is_superuser:
        messages.error(request, "Cannot impersonate staff or admin users.")
        return redirect("admin_user_search")
    
    # Save original admin info BEFORE switching users (session will be cleared on login)
    original_admin_id = request.user.id
    original_admin_username = request.user.username
    impersonate_started = timezone.now().isoformat()
    
    # Log the impersonation action (for the admin user)
    from .models import Notification, ImpersonationLog
    Notification.objects.create(
        user=request.user,
        kind="system",
        title="Impersonation Started",
        body=f"You are now viewing as {target_user.username} ({target_user.get_full_name() or 'No name'})",
        url=""
    )
    
    # Create impersonation log entry
    def get_client_ip(req):
        x_forwarded_for = req.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0]
        return req.META.get("REMOTE_ADDR", "")
    
    impersonation_log = ImpersonationLog.objects.create(
        admin_user=request.user,
        impersonated_user=target_user,
        ip_address=get_client_ip(request)
    )
    
    # Switch to the target user
    from django.contrib.auth import login
    login(request, target_user, backend='django.contrib.auth.backends.ModelBackend')
    
    # NOW set the impersonation session data (after login creates new session)
    request.session['impersonate_id'] = original_admin_id
    request.session['impersonate_username'] = original_admin_username
    request.session['impersonate_started'] = impersonate_started
    request.session['impersonation_log_id'] = impersonation_log.id
    
    messages.info(request, f"You are now viewing as {target_user.username}. Click 'Exit View As' to return to your admin account.")
    return redirect("accounts:profile")


@staff_member_required
def view_as_sponsor(request, user_id):
    """
    Admin impersonation feature - allows staff to view the site as a specific sponsor.
    Stores the original admin user ID in session for troubleshooting and audit purposes.
    """
    User = get_user_model()
    target_user = get_object_or_404(User, pk=user_id)
    
    # Prevent impersonating other staff members
    if target_user.is_staff or target_user.is_superuser:
        messages.error(request, "Cannot impersonate staff or admin users.")
        return redirect("admin_user_search")
    
    # Verify the target user is actually a sponsor
    if not target_user.groups.filter(name="sponsor").exists():
        messages.error(request, "Cannot impersonate non-sponsor users with this function.")
        return redirect("admin_user_search")
    
    # Save original admin info BEFORE switching users (session will be cleared on login)
    original_admin_id = request.user.id
    original_admin_username = request.user.username
    impersonate_started = timezone.now().isoformat()
    
    # Log the impersonation action (for the admin user)
    from .models import Notification, ImpersonationLog
    Notification.objects.create(
        user=request.user,
        kind="system",
        title="Sponsor Impersonation Started",
        body=f"You are now viewing as sponsor {target_user.username} ({target_user.get_full_name() or 'No name'})",
        url=""
    )
    
    # Create impersonation log entry
    def get_client_ip(req):
        x_forwarded_for = req.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0]
        return req.META.get("REMOTE_ADDR", "")
    
    impersonation_log = ImpersonationLog.objects.create(
        admin_user=request.user,
        impersonated_user=target_user,
        ip_address=get_client_ip(request)
    )
    
    # Switch to the target user
    from django.contrib.auth import login
    login(request, target_user, backend='django.contrib.auth.backends.ModelBackend')
    
    # NOW set the impersonation session data (after login creates new session)
    request.session['impersonate_id'] = original_admin_id
    request.session['impersonate_username'] = original_admin_username
    request.session['impersonate_started'] = impersonate_started
    request.session['impersonation_log_id'] = impersonation_log.id
    
    messages.info(request, f"You are now viewing as sponsor {target_user.username}. Click 'Exit View As' to return to your admin account.")
    
    # Redirect to sponsor driver search page (or profile if they don't have access)
    try:
        return redirect("accounts:sponsor_driver_search")
    except:
        return redirect("accounts:profile")


@login_required
def stop_impersonation(request):
    """
    Stop impersonating and return to original admin account.
    """
    impersonate_id = request.session.get('impersonate_id')
    impersonate_username = request.session.get('impersonate_username')
    
    if not impersonate_id:
        messages.warning(request, "You are not currently impersonating anyone.")
        return redirect("about")
    
    # Log the impersonation end
    impersonate_started = request.session.get('impersonate_started')
    impersonation_log_id = request.session.get('impersonation_log_id')
    duration = None
    if impersonate_started:
        from datetime import datetime
        start_time = datetime.fromisoformat(impersonate_started)
        duration = timezone.now() - start_time
        
        # Update impersonation log with end time and duration
        if impersonation_log_id:
            from .models import ImpersonationLog
            try:
                log_entry = ImpersonationLog.objects.get(id=impersonation_log_id)
                log_entry.ended_at = timezone.now()
                log_entry.duration_seconds = int(duration.total_seconds())
                log_entry.save()
            except ImpersonationLog.DoesNotExist:
                pass
    
    # Get the original admin user
    User = get_user_model()
    try:
        original_user = User.objects.get(pk=impersonate_id)
    except User.DoesNotExist:
        messages.error(request, "Original admin account not found. Please log in again.")
        auth_logout(request)
        return redirect("accounts:login")
    
    # Clear impersonation session data
    del request.session['impersonate_id']
    del request.session['impersonate_username']
    if 'impersonate_started' in request.session:
        del request.session['impersonate_started']
    if 'impersonation_log_id' in request.session:
        del request.session['impersonation_log_id']
    
    # Log back in as original admin
    from django.contrib.auth import login
    login(request, original_user, backend='django.contrib.auth.backends.ModelBackend')
    
    duration_str = f" (Duration: {duration})" if duration else ""
    messages.success(request, f"Returned to admin account: {original_user.username}{duration_str}")
    return redirect("admin_user_search")

def custom_permission_denied_view(request, exception=None):
    """Global 403 Forbidden handler."""
    return render(request, "errors/403_account_blocked.html", {
        "reason": "You do not have permission to access this page or your account has been restricted."
    }, status=403)


@staff_member_required
def download_error_log(request):
    """Allows admin to download the latest error log file."""
    log_path = settings.LOG_DIR / "error.log"

    if not log_path.exists():
        return HttpResponseNotFound("No error log file found.")

    date_str = request.GET.get("date")
    if date_str:
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponse("Invalid date format. Use YYYY-MM-DD.", status=400)

        # Filter lines that contain  date
        date_prefix = f"[{target_date.isoformat()}"
        filtered_lines = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if date_prefix in line:
                    filtered_lines.append(line)

        if not filtered_lines:
            return HttpResponse(f"No log entries found for {date_str}.", content_type="text/plain")

        response = HttpResponse("".join(filtered_lines), content_type="text/plain")
        response["Content-Disposition"] = f'attachment; filename="error_{date_str}.log"'
        return response

    # Default: send full log
    return FileResponse(open(log_path, "rb"), as_attachment=True, filename="error.log")


@staff_member_required
def manage_labels(request):
    """Admin page to create and view labels."""
    labels = CustomLabel.objects.all().order_by("name")
    if request.method == "POST":
        form = LabelForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Label saved successfully.")
            return redirect("accounts:manage_labels")
    else:
        form = LabelForm()
    return render(request, "accounts/manage_labels.html", {"form": form, "labels": labels})


@staff_member_required
def assign_labels(request):
    """Admin page to assign labels to drivers."""
    if request.method == "POST":
        form = AssignLabelForm(request.POST)
        if form.is_valid():
            driver = form.cleaned_data["driver"]
            labels = form.cleaned_data["labels"]
            driver.labels.set(labels)
            messages.success(request, f"Labels updated for {driver.user.username}.")
            return redirect("accounts:assign_labels")
    else:
        form = AssignLabelForm()
    return render(request, "accounts/assign_labels.html", {"form": form})


#Multifactor Authentication (MFA) Views
@login_required
@csrf_protect
def mfa_setup(request):
    """ 
    Set up MFA:
    - generate & store a TOTP secret if missing
    - render QR code for scanning
    - confirm 6 digit code from authenticator app
    """
    from .models import UserMFA

    mfa_record = UserMFA.for_user(request.user)

    #ensuring secret exists
    if not mfa_record.mfa_totp_secret:
        mfa_record.mfa_totp_secret = pyotp.random_base32()
        mfa_record.save()

    totp = pyotp.TOTP(mfa_record.mfa_totp_secret)

    #generate provisioning URI for QR code
    provisioning_uri = totp.provisioning_uri(
        name=request.user.username,
        issuer_name="TruckIncentive"
    )

    #generate QR code from pro. URI and base64
    qr_img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    #POST a code, verify it & enable MFA
    if request.method == "POST":
        submitted_code = request.POST.get("code", "").strip()
        if totp.verify(submitted_code):
            mfa_record.mfa_enabled = True
            mfa_record.save()
            messages.success(request, "Multi-factor authentication is now enabled.")
            return redirect("accounts:profile")
        else:
            messages.error(request, "That code was not valid. Try again.")

    return render(
        request,
        "accounts/mfa_setup.html",
        {
            "qr_b64": qr_b64,
            "already_enabled": mfa_record.mfa_enabled,
        }
    )

@csrf_protect
def mfa_challenge_view(request):
    from .models import UserMFA  # local import

    pending_user_id = request.session.get("pending_user_id")
    if not pending_user_id:
        messages.error(request, "Your login session expired. Please sign in again.")
        return redirect("accounts:login")

    # get the user we staged
    try:
        staged_user = User.objects.get(id=pending_user_id)
    except User.DoesNotExist:
        messages.error(request, "User not found. Please sign in again.")
        return redirect("accounts:login")

    # get or create their MFA record
    mfa_record = UserMFA.for_user(staged_user)

    # safety: if MFA isn't actually enabled anymore, just log them in and redirect
    if not mfa_record.mfa_enabled or not mfa_record.mfa_totp_secret:
        auth_login(request, staged_user, backend='django.contrib.auth.backends.ModelBackend')
        request.session.pop("pending_user_id", None)
        return redirect(landing_url_for(staged_user))  # uses your existing role logic

    if request.method == "GET":
        return render(request, "accounts/mfa_challenge.html")

    # POST: verify code
    submitted_code = request.POST.get("code", "").strip()
    totp = pyotp.TOTP(mfa_record.mfa_totp_secret)

    if totp.verify(submitted_code):
        # success -> finalize login
        auth_login(request, staged_user, backend='django.contrib.auth.backends.ModelBackend')
        request.session.pop("pending_user_id", None)
        return redirect(landing_url_for(staged_user))
    else:
        messages.error(request, "Invalid or expired code. Try again.")
        return render(request, "accounts/mfa_challenge.html")
    
@login_required
@require_POST
@csrf_protect
def mfa_toggle(request):
    """Enable or disable MFA for the logged-in user."""
    from .models import UserMFA
    action = request.POST.get("action")  # "enable" or "disable"
    code   = (request.POST.get("code") or "").strip()

    mfa = UserMFA.for_user(request.user)

    # Enabling: if no secret yet → must complete setup (QR scan) first
    if action == "enable" and not mfa.mfa_totp_secret:
        messages.info(request, "Please set up your authenticator app first.")
        return redirect("accounts:mfa_setup")

    # Must have a code to proceed
    if not code or len(code) < 6:
        messages.error(request, "Enter the 6-digit code from your authenticator app.")
        return redirect("accounts:profile")
    
    # Verify code against the user's secret
    totp = mfa.get_totp()
    if not totp:
        # Can't disable if not configured
        messages.error(request, "MFA is not configured yet. Set it up first.")
        return redirect("accounts:mfa_setup")

    # Time Window for clock drift
    if not totp.verify(code, valid_window=1):
        messages.error(request, "Invalid or expired code. Try again.")
        return redirect("accounts:profile")
    
    # Flips the switch
    if action == "enable":
        if mfa.mfa_enabled:
            messages.info(request, "MFA is already enabled.")
        else:
            mfa.mfa_enabled = True
            mfa.save(update_fields=["mfa_enabled"])
            messages.success(request, "MFA has been enabled on your account.")
    elif action == "disable":
        if not mfa.mfa_enabled:
            messages.info(request, "MFA is already disabled.")
        else:
            mfa.mfa_enabled = False
            mfa.save(update_fields=["mfa_enabled"])
            messages.success(request, "MFA has been disabled on your account.")
    else:
        messages.error(request, "Unknown action.")
    return redirect("accounts:profile")

class PasswordChangeNotifyView(PasswordChangeView):
    def form_valid(self, form):
        response = super().form_valid(form)
        notify_password_change(self.request.user)
        messages.success(self.request, "Password updated. A security notification was sent to your email.")
        return response
    
class PasswordResetConfirmNotifyView(PasswordResetConfirmView):
    def form_valid(self, form):
        response = super().form_valid(form)
        user = getattr(form, "get_user", None)
        user = user() if callable(user) else getattr(form, "user", None)
        if user:
            notify_password_change(user)
        messages.success(self.request, "Password reset successful. A security notification was sent to your email.")
        return response


# ============================================================================
# CHAT ROOM VIEWS
# ============================================================================

@login_required
def chat_rooms_list(request):
    """Display all chat rooms available to the user."""
    user = request.user
    chat_rooms = []
    
    # If user is a sponsor, show all chat rooms they own
    if user.groups.filter(name="sponsor").exists():
        chat_rooms = ChatRoom.objects.filter(sponsor=user)
    
    # If user is a driver, find chat rooms based on all their sponsors
    elif hasattr(user, "driver_profile"):
        profile = user.driver_profile
        driver_sponsors = list(profile.sponsors.all())
        
        # Also check legacy sponsor_name field
        if profile.sponsor_name:
            try:
                legacy_sponsor = User.objects.filter(
                    username=profile.sponsor_name,
                    groups__name="sponsor"
                ).first()
                if legacy_sponsor and legacy_sponsor not in driver_sponsors:
                    driver_sponsors.append(legacy_sponsor)
            except Exception:
                pass
        
        # Get or create chat room for each sponsor
        for sponsor in driver_sponsors:
            chat_room, created = ChatRoom.objects.get_or_create(
                sponsor=sponsor,
                defaults={"name": f"{sponsor.username}'s Team Chat"}
            )
            chat_rooms.append(chat_room)
    
    # Annotate each chat room with latest message and unread count
    for room in chat_rooms:
        room.latest_message = room.get_latest_message()
        room.unread_count = room.messages.exclude(sender=user).exclude(
            read_by__user=user,
            read_by__is_read=True
        ).count()
        room.participants_list = room.get_participants()
    
    context = {
        "chat_rooms": chat_rooms,
        "is_sponsor": user.groups.filter(name="sponsor").exists(),
    }
    
    return render(request, "accounts/chat_rooms_list.html", context)


@login_required
def chat_room_detail(request, room_id):
    """Display a specific chat room with messages."""
    user = request.user
    
    try:
        chat_room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        messages.error(request, "Chat room not found.")
        return redirect("accounts:chat_rooms_list")
    
    # Check if user has access to this chat room
    participants = chat_room.get_participants()
    if user not in participants:
        messages.error(request, "You don't have access to this chat room.")
        return redirect("accounts:chat_rooms_list")
    
    # Get all messages in the chat room
    chat_messages = chat_room.messages.select_related("sender").all()
    
    # Mark all messages as read for this user
    for message in chat_messages:
        if message.sender != user:
            message.mark_as_read(user)
    
    # Handle new message submission
    if request.method == "POST":
        message_text = request.POST.get("message", "").strip()
        if message_text:
            ChatMessage.objects.create(
                chat_room=chat_room,
                sender=user,
                message=message_text
            )
            # Update the chat room's updated_at timestamp
            chat_room.save()
            messages.success(request, "Message sent!")
            return redirect("accounts:chat_room_detail", room_id=room_id)
        else:
            messages.error(request, "Message cannot be empty.")
    
    context = {
        "chat_room": chat_room,
        "messages": chat_messages,
        "participants": participants,
        "is_sponsor": user.groups.filter(name="sponsor").exists(),
    }
    
    return render(request, "accounts/chat_room_detail.html", context)


@login_required
def get_chat_messages(request, room_id):
    """AJAX endpoint to get new messages for a chat room."""
    from django.http import JsonResponse
    
    user = request.user
    
    try:
        chat_room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        return JsonResponse({"error": "Chat room not found"}, status=404)
    
    # Check if user has access
    participants = chat_room.get_participants()
    if user not in participants:
        return JsonResponse({"error": "Access denied"}, status=403)
    
    # Get messages since a certain time (if provided)
    since = request.GET.get("since")
    messages_qs = chat_room.messages.select_related("sender")
    
    if since:
        try:
            since_dt = timezone.datetime.fromisoformat(since.replace('Z', '+00:00'))
            messages_qs = messages_qs.filter(created_at__gt=since_dt)
        except (ValueError, AttributeError):
            pass
    
    # Mark new messages as read
    for message in messages_qs:
        if message.sender != user:
            message.mark_as_read(user)
    
    messages_data = [{
        "id": msg.id,
        "sender": msg.sender.username,
        "sender_name": msg.sender.get_full_name() or msg.sender.username,
        "message": msg.message,
        "created_at": msg.created_at.isoformat(),
        "is_own": msg.sender == user,
    } for msg in messages_qs]
    
    return JsonResponse({"messages": messages_data})


@login_required
def send_chat_message(request, room_id):
    """AJAX endpoint to send a new message."""
    from django.http import JsonResponse
    
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    user = request.user
    
    try:
        chat_room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        return JsonResponse({"error": "Chat room not found"}, status=404)
    
    # Check if user has access
    participants = chat_room.get_participants()
    if user not in participants:
        return JsonResponse({"error": "Access denied"}, status=403)
    
    message_text = request.POST.get("message", "").strip()
    if not message_text:
        return JsonResponse({"error": "Message cannot be empty"}, status=400)
    
    # Create the message
    message = ChatMessage.objects.create(
        chat_room=chat_room,
        sender=user,
        message=message_text
    )
    
    # Update chat room timestamp
    chat_room.save()
    
    return JsonResponse({
        "success": True,
        "message": {
            "id": message.id,
            "sender": user.username,
            "sender_name": user.get_full_name() or user.username,
            "message": message.message,
            "created_at": message.created_at.isoformat(),
            "is_own": True,
        }
    })


# ============================================================================
# SPONSORSHIP REQUEST VIEWS
# ============================================================================

@login_required
def sponsorship_requests(request):
    """Sponsor portal: view all pending driver sponsorship requests."""
    if not request.user.groups.filter(name="sponsor").exists():
        messages.error(request, "Access denied. Only sponsors can view this page.")
        return redirect("accounts:profile")

    requests_qs = (
        SponsorshipRequest.objects
        .filter(to_user=request.user, status="pending")
        .select_related("from_user")
        .order_by("-created_at")
    )

    # Define context dict
    context = {
        "requests": requests_qs,
        "sponsor_pending_count": SponsorshipRequest.objects.filter(
            to_user=request.user, status="pending"
        ).count(),
    }

    return render(request, "accounts/sponsorship_requests.html", context)


@login_required
def approve_sponsorship(request, request_id):
    sponsorship_request = get_object_or_404(SponsorshipRequest, id=request_id)

    # Only the recipient of the request can approve
    if request.user != sponsorship_request.to_user:
        messages.error(request, "You are not authorized to approve this request.")
        return redirect("accounts:sponsorship_center")

    sponsorship_request.approve()
    messages.success(request, f"Sponsorship between {sponsorship_request.from_user.username} and {sponsorship_request.to_user.username} approved.")
    return redirect("accounts:sponsorship_center")


@login_required
def deny_sponsorship(request, request_id):
    """Deny a pending sponsorship request."""
    sr = get_object_or_404(SponsorshipRequest, pk=request_id, to_user=request.user)

    if sr.status != "pending":
        messages.warning(request, "This sponsorship request has already been processed.")
        return redirect("accounts:sponsorship_requests")

    sr.deny()
    messages.error(request, f"Sponsorship denied for driver {sr.from_user.username}.")
    return redirect("accounts:sponsorship_requests")

@login_required
@require_POST
def end_sponsorship(request, request_id):
    """Allow either driver or sponsor to end a sponsorship relationship.

    When a sponsorship is ended, the driver loses the points associated
    with that specific sponsor, but keeps points from other sponsors.
    """
    sponsorship = get_object_or_404(
        SponsorshipRequest,
        id=request_id,
        status="approved",
    )

    # Only involved users can end the sponsorship
    if request.user not in [sponsorship.from_user, sponsorship.to_user]:
        messages.error(request, "You are not authorized to modify this sponsorship.")
        return redirect("accounts:sponsorship_center")

    # Work out which side is driver vs sponsor (users, not profiles)
    if hasattr(sponsorship.from_user, "driver_profile"):
        driver_user = sponsorship.from_user
        sponsor_user = sponsorship.to_user
    else:
        driver_user = sponsorship.to_user
        sponsor_user = sponsorship.from_user

    driver_profile = driver_user.driver_profile

    # Remove sponsor from driver's profile M2M
    driver_profile.sponsors.remove(sponsor_user)

    # ---- Remove this sponsor's points from the driver ----
    # Only touch this one sponsor-driver pair; other sponsors stay intact.
    with transaction.atomic():
        wallets = (
            SponsorPointsAccount.objects
            .select_for_update()
            .filter(driver=driver_user, sponsor=sponsor_user)
        )

        for wallet in wallets:
            if wallet.balance > 0:
                reason = (
                    "Sponsorship ended; points from this sponsor have been removed."
                )
                try:
                    # Negative delta equal to current balance → wallet goes to 0
                    wallet.apply_points(
                        -wallet.balance,
                        reason=reason,
                        created_by=request.user,
                    )
                except Exception as e:
                    # Log but don't break the user flow
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "Failed to zero sponsor wallet on end_sponsorship: %s",
                        e,
                        exc_info=True,
                    )
    
    sponsorship.delete()

    messages.success(
        request,
        f"Sponsorship between {sponsor_user.username} and "
        f"{driver_user.username} has ended and points for this sponsor were removed.",
    )
    return redirect("accounts:sponsorship_center")


@login_required
def invite_driver(request):
    """Allow sponsors to invite (request) drivers for sponsorship."""
    if not request.user.groups.filter(name="sponsor").exists():
        messages.error(request, "Only sponsors can invite drivers.")
        return redirect("accounts:profile")

    # Only actual drivers (not sponsors, admins, or superusers)
    driver_users = (
        User.objects.filter(
            driver_profile__isnull=False,
            is_staff=False,
            is_superuser=False
        )
        .exclude(groups__name="sponsor")
        .order_by("username")
    )

    if request.method == "POST":
        driver_id = request.POST.get("driver_id")
        message = request.POST.get("message", "").strip()

        if not driver_id:
            messages.error(request, "Please select a driver.")
        else:
            driver = get_object_or_404(User, id=driver_id)

            # Prevent duplicate invitations
            already_invited = SponsorshipRequest.objects.filter(
                from_user=request.user,
                to_user=driver,
                status="pending"
            ).exists()

            if already_invited:
                messages.warning(request, f"You already have a pending request to {driver.username}.")
            else:
                SponsorshipRequest.objects.create(
                    from_user=request.user,
                    to_user=driver,
                    request_type="sponsor_to_driver",
                    message=message
                )
                messages.success(request, f"Sponsorship invitation sent to {driver.username}.")
            return redirect("accounts:sponsorship_requests")

    return render(request, "accounts/invite_driver.html", {"driver_users": driver_users})

@login_required
def sponsorship_center(request):
    """
    Unified Sponsorship Center for drivers and sponsors.
    Displays current sponsorships, pending requests, and invitations.
    """
    user = request.user
    is_sponsor = user.groups.filter(name="sponsor").exists()
    has_driver_profile = hasattr(user, "driver_profile")

    # Default querysets
    sent_requests = SponsorshipRequest.objects.none()
    received_requests = SponsorshipRequest.objects.none()
    current_relationships = []

    # Sponsors: see incoming requests from drivers + drivers they already sponsor
    if is_sponsor:
        received_requests = (
            SponsorshipRequest.objects.filter(to_user=user)
            .select_related("from_user")
            .order_by("-created_at")
        )
        sent_requests = (
            SponsorshipRequest.objects.filter(from_user=user)
            .select_related("to_user")
            .order_by("-created_at")
        )

        # Current sponsored drivers (approved relationships)
        current_relationships = (
            SponsorshipRequest.objects.filter(
                status="approved"
            )
            .filter(Q(from_user=user) | Q(to_user=user))
            .select_related("from_user", "to_user")
            .distinct()
        )

    # Drivers: see requests they've sent and sponsors who have approved them
    elif has_driver_profile:
        sent_requests = (
            SponsorshipRequest.objects.filter(from_user=user)
            .select_related("to_user")
            .order_by("-created_at")
        )
        received_requests = (
            SponsorshipRequest.objects.filter(to_user=user)
            .select_related("from_user")
            .order_by("-created_at")
        )

        # Current sponsors (from approved requests in either direction)
        current_relationships = (
            SponsorshipRequest.objects.filter(
                Q(from_user=user, status="approved") | Q(to_user=user, status="approved")
            )
            .select_related("from_user", "to_user")
            .distinct()
        )
    else:
        messages.error(request, "You do not have access to the Sponsorship Center.")
        return redirect("accounts:profile")

    context = {
        "is_sponsor": is_sponsor,
        "sent_requests": sent_requests,
        "received_requests": received_requests,
        "current_relationships": current_relationships,
    }

#     print(
#     "[DEBUG current_relationships]",
#     list(
#         SponsorshipRequest.objects.filter(
#             Q(from_user=request.user) | Q(to_user=request.user)
#         ).values("id", "from_user__username", "to_user__username", "status")
#     ),
# )

    return render(request, "accounts/sponsorship_center.html", context)

@login_required
def request_sponsor(request):
    """Allow drivers to request sponsorship from an existing sponsor user."""
    if not hasattr(request.user, "driver_profile"):
        messages.error(request, "Only drivers can send sponsorship requests.")
        return redirect("accounts:profile")

    sponsor_users = User.objects.filter(groups__name="sponsor").order_by("username")

    if request.method == "POST":
        sponsor_id = request.POST.get("sponsor_id")
        message = request.POST.get("message", "").strip()

        if not sponsor_id:
            messages.error(request, "Please select a sponsor.")
        else:
            sponsor = get_object_or_404(User, id=sponsor_id)
            SponsorshipRequest.objects.create(
                from_user=request.user,
                to_user=sponsor,
                request_type="driver_to_sponsor",
                message=message
            )
            messages.success(request, f"Sponsorship request sent to {sponsor.username}.")
            return redirect("accounts:profile")

    return render(request, "accounts/request_sponsor.html", {"sponsor_users": sponsor_users})


@login_required
def driver_sponsorship_requests(request):
    """Driver portal: view pending or reviewed sponsorship requests they have sent."""
    if not hasattr(request.user, "driver_profile"):
        messages.error(request, "Only drivers can view sponsorship requests.")
        return redirect("accounts:profile")

    requests_qs = (
        SponsorshipRequest.objects
        .filter(from_user=request.user)
        .select_related("to_user")
        .order_by("-created_at")
    )

    return render(
        request,
        "accounts/driver_sponsorship_requests.html",
        {"requests": requests_qs},
    )



@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def bulk_assign_sponsorship(request):
    """Admin: assign multiple sponsors to a driver or multiple drivers to a sponsor."""
    sponsors = User.objects.filter(groups__name="sponsor").order_by("username")
    drivers = User.objects.filter(driver_profile__isnull=False).order_by("username")

    if request.method == "POST":
        mode = request.POST.get("mode")  # 'sponsor_to_drivers' or 'drivers_to_sponsor'
        sponsor_id = request.POST.get("sponsor")
        driver_ids = request.POST.getlist("drivers")
        sponsor_ids = request.POST.getlist("sponsors")
        driver_id = request.POST.get("driver")

        if mode == "sponsor_to_drivers" and sponsor_id and driver_ids:
            sponsor = User.objects.get(id=sponsor_id)
            for driver_id in driver_ids:
                driver = User.objects.get(id=driver_id)
                driver.driver_profile.sponsors.add(sponsor)
            messages.success(request, f"Sponsor {sponsor.username} assigned to selected drivers.")

        elif mode == "drivers_to_sponsor" and driver_id and sponsor_ids:
            driver = User.objects.get(id=driver_id)
            for sponsor_id in sponsor_ids:
                sponsor = User.objects.get(id=sponsor_id)
                driver.driver_profile.sponsors.add(sponsor)
            messages.success(request, f"Selected sponsors assigned to driver {driver.username}.")

        else:
            messages.error(request, "Invalid selection or missing data.")
        return redirect("accounts:bulk_assign_sponsorship")

    return render(request, "accounts/admin_bulk_assign.html", {
        "sponsors": sponsors,
        "drivers": drivers,
    })


@login_required
def admin_manage_driver_sponsors(request, user_id):
    admin = request.user
    if not admin.is_staff:
        return redirect("accounts:profile")

    driver = get_object_or_404(User, id=user_id)
    if not hasattr(driver, "driver_profile"):
        messages.error(request, "Selected user is not a driver.")
        return redirect("accounts:admin_user_search")

    sponsor_users = User.objects.filter(groups__name="sponsor", is_active=True)

    if request.method == "POST":
        new_sponsor_ids = request.POST.getlist("sponsors")
        driver.driver_profile.sponsors.set(new_sponsor_ids)
        driver.driver_profile.save()

        messages.success(request, "Sponsors updated successfully.")
        return redirect("accounts:admin_user_search")

    current_sponsors = driver.driver_profile.sponsors.all()

    return render(
        request,
        "accounts/admin_manage_driver_sponsors.html",
        {
            "driver": driver,
            "all_sponsors": sponsor_users,
            "current_sponsors": current_sponsors,
        },
    )