from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from weblate.accounts.views import social_complete
from weblate.utils.ratelimit import check_rate_limit

from .firebase_auth import PebbleLoginDenied, enabled


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
