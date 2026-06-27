from django.conf import settings
from django.shortcuts import redirect


class SimplePasswordMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        password = settings.ADMIN_PASSWORD
        if not password or request.path in {"/login", "/healthz"} or request.path.startswith("/static/"):
            return self.get_response(request)
        if request.session.get("admin_password_ok"):
            return self.get_response(request)
        if request.method == "POST" and request.path == "/login":
            return self.get_response(request)
        return redirect("login")
