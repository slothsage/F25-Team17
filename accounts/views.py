from django.contrib import messages
from django import forms
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
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
from django.db import connections
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from urllib.parse import quote
from django.templatetags.static import static

from .forms import RegistrationForm  
from .models import PasswordPolicy
from .models import DriverProfile
from .models import Notification
from .models import PointsLedger
from .models import Message, MessageRecipient
from .forms import MessageComposeForm
from .forms import NotificationPreferenceForm

from .forms import ProfileForm, DeleteAccountForm
from .models import DriverNotificationPreference
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.db.models import Q
from django import db as django_db
from django.db import models
from shop.models import Order
from shop.utils import order_is_delayed
from django.core.paginator import Paginator
from django.http import HttpResponse
import csv

from django.contrib.auth.views import LoginView
from django.shortcuts import resolve_url
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django import forms
from django.contrib.admin.views.decorators import staff_member_required

User = get_user_model()

@login_required
def profile(request):
    DriverProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/profile.html")

@login_required
def profile_edit(request):
    profile, _ = DriverProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES,instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
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
    if sponsor_q:
        sponsor_users_qs = sponsor_users_qs.filter(
            Q(username__icontains=sponsor_q) |
            Q(email__icontains=sponsor_q)
        )
    sponsor_users_qs = sponsor_users_qs.order_by("username")
    
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

    return render(
        request,
        "accounts/admin_user_search.html",
        {
            "drivers": drivers_page,
            "sponsors": sponsors,
            "sponsor_users": sponsor_users_qs,
            "q": q,
            "sponsor_q": sponsor_q,
            "total_drivers_count": total_drivers_count,
            "drivers_matching_count": drivers_matching_count,
            "total_sponsors_count": total_sponsors_count,
            "sponsors_matching_count": sponsors_matching_count,
        },
    )

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, driver=request.user)
    is_delayed = order_is_delayed(order)
    return render(request, "shop/order_detail.html", {"order": order, "is_delayed": is_delayed})

class FrontLoginView(LoginView):
    template_name = "registration/login.html"

    def form_valid(self, form):
        # user_type is chosen on the login form (driver/sponsor/admin)
        user = form.get_user()
        user_type = self.request.POST.get("user_type")

        # log the user in using parent behavior
        response = super().form_valid(form)

        # Enforce user_type role restrictions
        if user_type == "driver":
            # disallow staff/superuser choosing driver (admins must pick admin)
            if user.is_staff or user.is_superuser:
                auth_logout(self.request)
                messages.error(self.request, "Admin accounts must sign in as Admin. Please choose Admin on the login form.")
                return redirect("login")
            # must have a DriverProfile
            if not hasattr(user, "driver_profile"):
                auth_logout(self.request)
                messages.error(self.request, "This account is not a driver. Please select the correct user type.")
                return redirect("accounts:login")

        if user_type == "sponsor":
            # disallow staff/superuser choosing sponsor
            if user.is_staff or user.is_superuser:
                auth_logout(self.request)
                messages.error(self.request, "Admin accounts must sign in as Admin. Please choose Admin on the login form.")
                return redirect("login")
            # must be in sponsor group
            if not user.groups.filter(name="sponsor").exists():
                auth_logout(self.request)
                messages.error(self.request, "This account is not a sponsor. Please select the correct user type.")
                return redirect("login")

        if user_type == "admin":
            if not (user.is_staff or user.is_superuser):
                auth_logout(self.request)
                messages.error(self.request, "This account is not an admin. Please select the correct user type.")
                return redirect("login")

        # if admin and has privileges, go to admin landing
        if user_type == "admin" and (user.is_staff or user.is_superuser):
            return redirect(resolve_url("admin_user_search"))

        return response


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
def message_detail(request, pk: int):
    item = get_object_or_404(MessageRecipient.objects.select_related("message", "message__author"), 
                            pk=pk, user=request.user)
    if not item.is_read:
        item.is_read = True
        item.save(update_fields = ["is_read"])
    return render(request, "accounts/message_detail.html", {"item":item})

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
            sponsor_group, _ = Group.objects.get_or_create(name="sponsor")
            user.groups.add(sponsor_group)

            messages.success(request, f"Sponsor '{username}' created.")
            return redirect("admin_user_search")
    else:
        form = SponsorCreateForm()

    return render(request, "accounts/create_sponsor.html", {"form": form})


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
    rows = (MessageRecipient.objects
        .select_related("message", "message__author")
        .filter(user=request.user)
        .order_by("-delivered_at"))
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
def notifications_feed(request):
    rows = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(request, "accounts/notifications_feed.html", {"rows": rows})

@login_required
def points_history(request):
    rows = PointsLedger.objects.filter(user=request.user).order_by("-created_at")
    balance = rows.aggregate(s=Sum("delta"))["s"] or 0
    return render(request, "accounts/points_history.html", {"rows": rows, "balance": balance})


@login_required
def contact_sponsor(request):
    profile = getattr(request.user, "driver_profile", None)

    # If driver has no sponsor info, show a friendly error
    if not profile or not profile.sponsor_email:
        return render(request, "accounts/contact_sponsor.html", {
            "error": "No sponsor contact information available.",
        })

    sponsor = profile.sponsor_name or "Your Sponsor"
    email = profile.sponsor_email

    # Pass data to the template for display (not redirect)
    return render(request, "accounts/contact_sponsor.html", {
        "email": email,
        "sponsor": sponsor,
    })



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