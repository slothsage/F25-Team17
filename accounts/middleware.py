import datetime
from django.utils.timezone import now
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout


class ActiveUserSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated:
            session = request.session
            session['last_activity'] = now().isoformat()
            session['ip_address'] = self.get_client_ip(request)
            session['user_id'] = request.user.id
            session.modified = True 

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0]
        return request.META.get("REMOTE_ADDR")
    

class BlockLockedUserMiddleware:
    """
    Prevent locked users from accessing the site.
    Checks user’s DriverProfile.is_locked before processing any request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            profile = getattr(user, "driverprofile", None)
            if profile and profile.is_locked:
                logout(request)
                messages.error(request, "Your account has been locked by an administrator.")
                return redirect("accounts:login")

        return self.get_response(request)