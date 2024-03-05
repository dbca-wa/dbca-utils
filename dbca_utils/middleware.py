from django import http, VERSION
from django.conf import settings
from django.contrib.auth import login, logout, get_user_model
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import SimpleLazyObject
from django.utils import timezone
from django.contrib.auth.middleware import AuthenticationMiddleware, get_user

from dbca_utils.utils import env

ENABLE_AUTH2_GROUPS = env("ENABLE_AUTH2_GROUPS", default=False)
LOCAL_USERGROUPS = env("LOCAL_USERGROUPS", default=[])
User = get_user_model()


def sync_usergroups(user, groups):
    from django.contrib.auth.models import Group

    usergroups = (
        [Group.objects.get_or_create(name=name)[0] for name in groups.split(",")] if groups else []
    )
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
                request.user = SimpleLazyUser(
                    lambda: get_user(request), request, groups
                )
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
            (
                request.path.startswith("/logout")
                or request.path.startswith("/admin/logout")
                or request.path.startswith("/ledger/logout")
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
            # auth2 not enabled
            return

        if VERSION < (2, 0):
            user_authenticated = request.user.is_authenticated()
        else:
            user_authenticated = request.user.is_authenticated

        # Auth2 is enabled.
        # Request user is not authenticated.
        if not user_authenticated:
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

            if (
                attributemap["email"]
                and User.objects.filter(email__iexact=attributemap["email"]).exists()
            ):
                user = User.objects.filter(email__iexact=attributemap["email"])[0]
            elif (
                User.__name__ != "EmailUser"
                and User.objects.filter(username__iexact=attributemap["username"]).exists()
            ):
                user = User.objects.filter(username__iexact=attributemap["username"])[0]
            else:
                user = User(last_login=timezone.localtime())

            # Set the user's details from the supplied information.
            user.__dict__.update(attributemap)
            user.save()
            user.backend = "django.contrib.auth.backends.ModelBackend"

            # Log the user in.
            login(request, user)

            # Synchronize the user groups
            if ENABLE_AUTH2_GROUPS and "HTTP_X_GROUPS" in request.META:
                groups = request.META["HTTP_X_GROUPS"] or None
                sync_usergroups(user, groups)
                request.session["usergroups"] = groups
