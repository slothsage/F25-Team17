from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Auth
    path("login/", views.FrontLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # Password change (while logged in)
    path("password/change/", auth_views.PasswordChangeView.as_view(
        template_name="registration/password_change_form.html"), name="password_change"),
    path("password/change/done/", auth_views.PasswordChangeDoneView.as_view(
        template_name="registration/password_change_done.html"), name="password_change_done"),

    # Password reset (forgot password)
    path("password/reset/", auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html"), name="password_reset"),
    path("password/reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html"), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html"), name="password_reset_complete"),

    # Driver profile
    path("", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("account/delete/", views.delete_account, name="delete_account"),
    path("profile/preview/", views.profile_preview, name="profile_preview"),

]