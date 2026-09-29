"""Narrow Firebase browser permissions to its actual login page."""

from django.conf import settings
from weblate.middleware import SecurityMiddleware

from .firebase_auth import enabled


class PebbleSecurityMiddleware(SecurityMiddleware):
    def process_response(self, request, response):
        response = super().process_response(request, response)
        if (
            response.status_code != 200
            or not getattr(request, "peblate_firebase_page", False)
            or not enabled()
        ):
            return response
        directives = {}
        for directive in response["Content-Security-Policy"].split(";"):
            name, *values = directive.split()
            directives[name] = set(values)
        auth_origin = f"https://{settings.PEBLATE_FIREBASE_AUTH_DOMAIN}"
        # Native social:begin permits inline provider forms; this page uses
        # only external scripts and JSON data, so does not need that exception.
        directives["script-src"].discard("'unsafe-inline'")
        directives["script-src"].update(
            {
                "https://www.gstatic.com/firebasejs/10.12.2/",
                "https://apis.google.com",
            }
        )
        directives["connect-src"].update(
            {
                "https://identitytoolkit.googleapis.com",
                "https://securetoken.googleapis.com",
                auth_origin,
            }
        )
        directives["frame-src"].discard("'none'")
        directives["frame-src"].add(auth_origin)
        response["Content-Security-Policy"] = "; ".join(
            f"{name} {' '.join(sorted(values))}" for name, values in directives.items()
        )
        response["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        return response
