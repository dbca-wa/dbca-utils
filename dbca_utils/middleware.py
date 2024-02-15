from django import http
from django.conf import settings
from django.contrib.auth import login, logout, get_user_model
from django.utils.deprecation import MiddlewareMixin

User = get_user_model()


class SSOLoginMiddleware(MiddlewareMixin):
    """Django middleware to process HTTP requests containing headers set by the Auth2
    SSO service, specificially:
    - `HTTP_REMOTE_USER`
    - `HTTP_X_LAST_NAME`
    - `HTTP_X_FIRST_NAME`
    - `HTTP_X_EMAIL`

    The middleware assesses requests containing these headers, and (having deferred user
    authentication to the upstream service), retrieves the local Django User and logs
    the user in automatically.

    If the request path starts with one of the defined logout paths and a `HTTP_X_LOGOUT_URL`
    value is set in the response, log out the user and redirect to that URL instead.
    """

    def process_request(self, request):

        # Logout headers included with request.
        if (
            (
                request.path.startswith("/logout")
                or request.path.startswith("/admin/logout")
            )
            and "HTTP_X_LOGOUT_URL" in request.META
            and request.META["HTTP_X_LOGOUT_URL"]
        ):
            logout(request)
            return http.HttpResponseRedirect(request.META["HTTP_X_LOGOUT_URL"])

        # Auth2 is not enabled, skip further processing.
        if (
            "HTTP_REMOTE_USER" not in request.META
            or not request.META["HTTP_REMOTE_USER"]
        ):
            return

        # Auth2 is enabled.
        # Request user is not authenticated.
        if not request.user.is_authenticated:
            attributemap = {
                "username": "HTTP_REMOTE_USER",
                "last_name": "HTTP_X_LAST_NAME",
                "first_name": "HTTP_X_FIRST_NAME",
                "email": "HTTP_X_EMAIL",
            }

            for key, value in attributemap.items():
                if value in request.META:
                    attributemap[key] = request.META[value]

            # Optional setting: projects may define accepted user email domains either as
            # a list of strings, or a single string.
            if (
                hasattr(settings, "ALLOWED_EMAIL_SUFFIXES")
                and settings.ALLOWED_EMAIL_SUFFIXES
            ):
                allowed = settings.ALLOWED_EMAIL_SUFFIXES
                if isinstance(settings.ALLOWED_EMAIL_SUFFIXES, str):
                    allowed = [settings.ALLOWED_EMAIL_SUFFIXES]
                if not any(
                    [attributemap["email"].lower().endswith(x) for x in allowed]
                ):
                    return http.HttpResponseForbidden()

            # Check if the supplied request user email already exists as a local User.
            if (
                attributemap["email"]
                and User.objects.filter(email__iexact=attributemap["email"]).exists()
            ):
                user = User.objects.get(email__iexact=attributemap["email"])
            else:
                user = User()

            # Set the user's details from the supplied information.
            user.__dict__.update(attributemap)
            user.save()
            user.backend = "django.contrib.auth.backends.ModelBackend"

            # Log the user in.
            login(request, user)
