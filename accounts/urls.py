from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from django.conf.urls import static
from django.conf import settings
from . import views
from .forms import PolicyPasswordChangeForm

app_name = "accounts"

urlpatterns = [
    # Auth
    path("login/", views.FrontLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),

    # Messaging
    path("messages/", views.messages_inbox, name="messages_inbox"),
    path("messages/sent/", views.messages_sent, name="messages_sent"),
    path("messages/compose/", views.messages_compose, name="message_compose"),
    path("messages/item/<int:pk>/", views.message_detail, name="messages_detail"),
    
    
    # Password change (while logged in)
    path("password/change/", auth_views.PasswordChangeView.as_view(
        form_class=PolicyPasswordChangeForm,
        template_name="registration/password_change_form.html",
        success_url=reverse_lazy("accounts:password_change_done"),
    ), name="password_change"),
    path("password/change/done/", auth_views.PasswordChangeDoneView.as_view(
        template_name="registration/password_change_done.html"), name="password_change_done"),

    # Password reset (forgot password)
    path("password/reset/", auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        success_url=reverse_lazy("accounts:password_reset_done")), name="password_reset"),
    path("password/reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html"), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html"), name="password_reset_complete"),

    # Admin-only password policy page 
    path("policy/", views.edit_policy, name="edit_policy"),

    # Admin: login activity audit
    path("admin/login-activity/", views.login_activity, name="login_activity"),

    # Sponsor-facing driver search
    path("sponsor/drivers/", views.sponsor_driver_search, name="sponsor_driver_search"),

    # Admin-triggered password actions 
    path("admin/users/<int:user_id>/reset-link/", views.send_reset_link, name="admin_send_reset_link"),
    path("admin/users/<int:user_id>/temp-password/", views.set_temporary_password, name="admin_set_temp_password"),
    path("admin/users/<int:user_id>/set-password/", views.admin_set_password, name="admin_set_password"),
    path("admin/users/<int:user_id>/set-timeout/", views.admin_set_timeout, name="admin_set_timeout"),

    # Force logout
    path("admin/users/<int:user_id>/force-logout/", views.force_logout_user, name="admin_force_logout_user"),
    # Active sessions
    path("admin/user/<int:user_id>/toggle-active/", views.toggle_user_active, name="toggle_user_active"),
    path("admin/sessions/", views.admin_active_sessions, name="admin_active_sessions"),
    path("admin/sessions/terminate/<str:session_key>/", views.terminate_session, name="terminate_session"),
    # Lock user
    path("admin/user/<int:user_id>/toggle-lock/", views.toggle_lock_user, name="toggle_lock_user"),
    # Suspend
    path("admin/user/<int:user_id>/toggle-suspend/", views.toggle_suspend_user, name="toggle_suspend_user"),
    # Driver profile
    path("", views.profile, name="profile"),
    path("profile/", views.profile, name="profile_detail"),  # For convenience
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("account/delete/", views.delete_account, name="delete_account"),
    path("profile/preview/", views.profile_preview, name="profile_preview"),

    # Notification preferences
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/history/", views.notifications_history, name="notifications_history"),
    path("notifications/feed/", views.notifications_feed, name="notifications_feed"),
    path("notifications/clear/", views.notifications_clear, name="notifications_clear"),
    path("notifications/settings/", views.notification_settings, name="notification_settings"),
    
    
    path("points/", views.points_history, name="points_history"),
    path("contact-sponsor/", views.contact_sponsor, name="contact_sponsor"),

    path("api/suggest/drivers/", views.api_driver_suggest, name="api_driver_suggest"),
    path("api/suggest/sponsors/", views.api_sponsor_suggest, name="api_sponsor_suggest"),
    
    # Support tickets
    path("support/submit/", views.submit_ticket, name="submit_ticket"),
    path("admin/tickets/", views.admin_tickets, name="admin_tickets"),
    path("admin/tickets/<int:ticket_id>/resolve/", views.resolve_ticket, name="resolve_ticket"),
    
    # Complaints
    path("complaints/submit/", views.submit_complaint, name="submit_complaint"),
    path("admin/complaints/", views.admin_complaints, name="admin_complaints"),
    path("admin/complaints/<int:complaint_id>/resolve/", views.resolve_complaint, name="resolve_complaint"),
]