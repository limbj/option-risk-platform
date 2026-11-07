"""Exercise the global DRF session/CSRF policy using test-only routes."""

import pytest
from django.http import JsonResponse
from django.test import override_settings
from django.urls import path
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.test import APIClient


@api_view(["POST"])
def session_protected_action(request):
    return Response({"username": request.user.get_username()})


@ensure_csrf_cookie
def csrf_cookie(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("protected/", session_protected_action),
    path("csrf/", csrf_cookie),
]


@override_settings(ROOT_URLCONF=__name__)
def test_unauthenticated_session_request_is_denied():
    response = APIClient(enforce_csrf_checks=True).post("/protected/", {}, format="json")
    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_authenticated_write_requires_matching_csrf_token(django_user_model):
    user = django_user_model.objects.create_user(username="session-user")
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)

    missing_token = client.post("/protected/", {}, format="json")
    assert missing_token.status_code == 403
    assert "CSRF" in str(missing_token.data)

    client.get("/csrf/")
    accepted = client.post(
        "/protected/", {}, format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"username": "session-user"}
