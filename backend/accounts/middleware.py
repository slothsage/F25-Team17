import datetime
from django.utils.timezone import now

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
            session.modified = True  # ensures it gets saved

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0]
        return request.META.get("REMOTE_ADDR")