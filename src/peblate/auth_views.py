from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from weblate.accounts.views import (
    WeblateLoginView,
    redirect_single,
    social_auth,
    social_complete,
)
from weblate.utils.ratelimit import check_rate_limit

from .firebase_auth import PebbleLoginDenied, enabled


class ExistingLoginView(WeblateLoginView):
    template_name = "pebble/existing_login.html"


@never_cache
@login_not_required
@csrf_protect
def pebble_login(request):
    if request.user.is_authenticated or request.method != "GET":
        # Preserve existing password submissions and native 2FA handling.
        return ExistingLoginView.as_view()(request)
    if enabled():
        return redirect_single(request, "pebble")
    return render(request, "pebble/login.html", {"title": "Pebble sign-in"})


@never_cache
@login_not_required
@csrf_protect
def pebble_begin(request):
    if request.method == "GET":
        # Refreshes/bookmarks must enter through the CSRF-protected POST flow.
        response = redirect("login")
        if request.GET.get("next"):
            response["Location"] += "?" + urlencode({"next": request.GET["next"]})
        return response
    return social_auth(request, "pebble")


@never_cache
@login_not_required
@csrf_protect
def pebble_register(request):
    if request.user.is_authenticated:
        return redirect("profile")
    # Never accept the native email signup form, including invitation sessions.
    if request.method != "GET":
        return render(
            request,
            "pebble/login.html",
            {
                "title": "Create an account",
                "error": "Sign up using your Pebble account.",
            },
            status=403,
        )
    if enabled() and settings.REGISTRATION_OPEN:
        return redirect_single(request, "pebble")
    return render(
        request,
        "pebble/login.html",
        {
            "title": "Create an account",
            "error": "New registrations are not enabled yet.",
        },
    )


@never_cache
@login_not_required
@sensitive_post_parameters("id_token")
@csrf_protect
def pebble_complete(request):
    # Native OAuth callbacks are CSRF-exempt. This callback accepts a Firebase
    # token from our own form, so requires CSRF protection instead. Strip the
    # bearer token before native code serializes data for partial pipelines.
    request.peblate_id_token = request.POST.get("id_token", "")
    request.POST = request.POST.copy()
    request.POST.pop("id_token", None)
    try:
        if not enabled():
            raise PebbleLoginDenied("Pebble sign-in is not available yet.")
        if request.method == "POST" and not check_rate_limit("pebble_login", request):
            raise PebbleLoginDenied(
                "Too many sign-in attempts. Please try again later."
            )
        return social_complete(request, "pebble")
    except PebbleLoginDenied as error:
        return render(
            request,
            "pebble/login.html",
            {"title": "Pebble sign-in", "error": str(error)},
            status=403,
        )
    finally:
        del request.peblate_id_token
