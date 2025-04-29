from django import http
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.middleware import AuthenticationMiddleware, get_user
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import SimpleLazyObject
from markupsafe import escape

from dbca_utils.utils import env

ENABLE_AUTH2_GROUPS = env("ENABLE_AUTH2_GROUPS", default=False)
LOCAL_USERGROUPS = env("LOCAL_USERGROUPS", default=[])
User = get_user_model()


def sync_usergroups(user, groups=None):
    from django.contrib.auth.models import Group

    if groups:
        usergroups = [Group.objects.get_or_create(name=name)[0] for name in groups.split(",")]
    else:
        usergroups = []

    usergroups.sort(key=lambda o: o.id)
    existing_usergroups = list(user.groups.exclude(name__in=LOCAL_USERGROUPS).order_by("id"))
    index1 = 0
    index2 = 0
    len1 = len(usergroups)
    len2 = len(existing_usergroups)

    while True:
        group1 = usergroups[index1] if index1 < len1 else None
        group2 = existing_usergroups[index2] if index2 < len2 else None
        if not group1 and not group2:
            break
        if not group1:
            user.groups.remove(group2)
            index2 += 1
        elif not group2:
            user.groups.add(group1)
            index1 += 1
        elif group1.id == group2.id:
            index1 += 1
            index2 += 1
        elif group1.id < group2.id:
            user.groups.add(group1)
            index1 += 1
        else:
            user.groups.remove(group2)
            index2 += 1


class SimpleLazyUser(SimpleLazyObject):
    def __init__(self, func, request, groups):
        super().__init__(func)
        self.request = request
        self.usergroups = groups

    def __getattr__(self, name):
        if name == "groups":
            sync_usergroups(self._wrapped, self.usergroups)
            self.request.session["usergroups"] = self.usergroups

        return super().__getattr__(name)


# Monkey patch AuthenticationMiddleware to add logic to process user groups.
if ENABLE_AUTH2_GROUPS:
    original_process_request = AuthenticationMiddleware.process_request

    def _process_request(self, request):
        if "HTTP_X_GROUPS" in request.META:
            groups = request.META["HTTP_X_GROUPS"] or None
            existing_groups = request.session.get("usergroups")
            if groups != existing_groups:
                # User group is changed.
                request.user = SimpleLazyUser(lambda: get_user(request), request, groups)
                return
        original_process_request(self, request)

    AuthenticationMiddleware.process_request = _process_request


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
            (request.path.startswith("/logout") or request.path.startswith("/admin/logout") or request.path.startswith("/ledger/logout"))
            and "HTTP_X_LOGOUT_URL" in request.META
            and request.META["HTTP_X_LOGOUT_URL"]
        ):
            logout(request)
            return http.HttpResponseRedirect(request.META["HTTP_X_LOGOUT_URL"])

        # Auth2 is not enabled, skip further processing.
        if "HTTP_REMOTE_USER" not in request.META or not request.META["HTTP_REMOTE_USER"]:
            # auth2 not enabled
            return

        # Auth2 is enabled.
        # Security check: if the logged-in request user's email does not match the email
        # returned from Auth2, invalidate the current request session and force a new session
        # using the returned SSO values.
        if request.user.is_authenticated and request.user.email != request.META["HTTP_X_EMAIL"]:
            logout(request)

        # Request user is not authenticated locally: obtain user attributes from the request.META dict
        # returned by SSO.
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

            # Sanitise first_name and last_name values, because end-users have control over these
            # values and could conceivably inject malicious values into them (e.g. a XSS attack).
            if "first_name" in attributemap:
                attributemap["first_name"] = str(escape(attributemap["first_name"]))
            if "last_name" in attributemap:
                attributemap["last_name"] = str(escape(attributemap["last_name"]))

            # Optional setting: projects may define accepted user email domains either as
            # a list of strings, or a single string.
            if hasattr(settings, "ALLOWED_EMAIL_SUFFIXES") and settings.ALLOWED_EMAIL_SUFFIXES:
                if isinstance(settings.ALLOWED_EMAIL_SUFFIXES, str):
                    allowed_email_suffixes = list(settings.ALLOWED_EMAIL_SUFFIXES)
                else:
                    allowed_email_suffixes = settings.ALLOWED_EMAIL_SUFFIXES
                # If the user email suffix is not in the allowed list, return a 404 response.
                if not any([attributemap["email"].lower().endswith(suffix) for suffix in allowed_email_suffixes]):
                    return http.HttpResponseForbidden()

            # Check for an existing User instance.
            if attributemap["email"] and User.objects.filter(email__iexact=attributemap["email"]).exists():
                user = User.objects.filter(email__iexact=attributemap["email"])[0]
            elif User.__name__ != "EmailUser" and User.objects.filter(username__iexact=attributemap["username"]).exists():
                user = User.objects.filter(username__iexact=attributemap["username"])[0]
            else:
                user = User(last_login=timezone.localtime())

            # Set the user's details from the supplied information.
            user.__dict__.update(attributemap)
            user.save()
            user.backend = "django.contrib.auth.backends.ModelBackend"

            # Log the user in.
            login(request, user)

            # Synchronize the user groups.
            if ENABLE_AUTH2_GROUPS and "HTTP_X_GROUPS" in request.META:
                groups = request.META["HTTP_X_GROUPS"] or None
                sync_usergroups(user, groups)
                request.session["usergroups"] = groups
