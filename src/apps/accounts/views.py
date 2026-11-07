import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST


def session_payload(request):
    user = request.user
    return {
        "authenticated": user.is_authenticated,
        "user": {"id": user.pk, "username": user.get_username()} if user.is_authenticated else None,
        "csrfToken": get_token(request),
    }


@require_GET
@ensure_csrf_cookie
def session_view(request):
    return JsonResponse(session_payload(request))


@require_POST
@csrf_protect
def login_view(request):
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Expected a JSON object"}, status=400)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("username"), str)
        or not isinstance(data.get("password"), str)
    ):
        return JsonResponse({"detail": "username and password are required"}, status=400)
    user = authenticate(request, username=data["username"], password=data["password"])
    if user is None:
        return JsonResponse({"detail": "Invalid credentials"}, status=400)
    login(request, user)
    return JsonResponse(session_payload(request))


@require_POST
@csrf_protect
def logout_view(request):
    logout(request)
    return JsonResponse(session_payload(request))
