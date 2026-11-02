import logging
from urllib.parse import urlparse

from django import http
from django.contrib.auth import get_user_model, login, logout, models
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.utils.html import strip_tags
from markupsafe import escape

from dbca_utils.utils import env

logger = logging.getLogger(__name__)

ENABLE_AUTH2_GROUPS = env("ENABLE_AUTH2_GROUPS", default=False)
LOCAL_USERGROUPS = env("LOCAL_USERGROUPS", default=[])
GROUP_SEPARATOR = env("GROUP_SEPARATOR", default=",")
if not GROUP_SEPARATOR:
    # str.split("") raises ValueError, which would break every SSO login.
    logger.warning("GROUP_SEPARATOR is empty; falling back to ','.")
    GROUP_SEPARATOR = ","
User = get_user_model()

# Optional setting: projects may define logout urls either as
# a list of strings, or a single string.
LOGOUT_URLS = env("LOGOUT_URLS", default=["/logout", "/admin/logout", "/ledger/logout", "/sso/auth_logout"])


def is_logout_url(path):
    """Return True if ``path`` is one of the configured logout paths.

    Paths are compared exactly (ignoring a trailing slash). A prefix match
    would also match unrelated routes such as ``/logout-confirm`` or
    ``/logoutx``, logging the user out of pages that are not logout endpoints.
    """
    normalised_path = (path or "").rstrip("/")
    return any(normalised_path == url.rstrip("/") for url in LOGOUT_URLS if isinstance(url, str))

# After logout the middleware redirects to the URL supplied by the SSO proxy.
# Only relative URLs and HTTPS URLs within this domain (or its subdomains) are
# permitted, to prevent the header being used as an open redirect.
ALLOWED_LOGOUT_DOMAIN = "dbca.wa.gov.au"


def is_allowed_logout_url(url):
    """Return True if ``url`` is safe to redirect to after logout.

    Relative URLs are allowed (they stay on the current host). Absolute URLs
    must use HTTPS and point at ``ALLOWED_LOGOUT_DOMAIN`` or one of its
    subdomains.
    """
    if not url:
        return False

    # Browsers treat backslashes as forward slashes, so normalise them before
    # parsing to avoid bypasses such as "https://evil.example\\@dbca.wa.gov.au".
    url = url.strip().replace("\\", "/")

    # Allow same-site relative URLs, but not protocol-relative ones ("//host").
    if url.startswith("/") and not url.startswith("//"):
        return True

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower().rstrip(".")
    return host == ALLOWED_LOGOUT_DOMAIN or host.endswith("." + ALLOWED_LOGOUT_DOMAIN)


# Optional setting: projects may define accepted user email domains either as
# a list of strings, or a single string.
ALLOWED_EMAIL_SUFFIXES = env("ALLOWED_EMAIL_SUFFIXES", default=[])
if ALLOWED_EMAIL_SUFFIXES:
    if any(not isinstance(suffix, str) for suffix in ALLOWED_EMAIL_SUFFIXES):
        raise ValueError("ALLOWED_EMAIL_SUFFIXES must be a list of strings")

    if len(ALLOWED_EMAIL_SUFFIXES) == 1:
        ALLOWED_EMAIL_SUFFIXES = ALLOWED_EMAIL_SUFFIXES[0]
        f_check_email_suffix = lambda email: email.endswith(ALLOWED_EMAIL_SUFFIXES)
    else:
        f_check_email_suffix = lambda email: any(email.endswith(suffix) for suffix in ALLOWED_EMAIL_SUFFIXES)
else:
    f_check_email_suffix = None

attributemap = {
    "username": "HTTP_REMOTE_USER",
    "email": "HTTP_X_EMAIL",
    "last_name": "HTTP_X_LAST_NAME",
    "first_name": "HTTP_X_FIRST_NAME",
}
guest = models.AnonymousUser()


def sync_usergroups(user, groups=None):
    from django.contrib.auth.models import Group

    if groups:
        usergroups = [Group.objects.get_or_create(name=name.strip())[0] for name in groups.split(GROUP_SEPARATOR) if name.strip()]
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


class SSOLoginMiddleware(MiddlewareMixin):
    """Django middleware to process HTTP requests containing headers set by the Auth2
    SSO service, specificially:
    - `HTTP_REMOTE_USER`
    - `HTTP_X_EMAIL`
    - `HTTP_X_LAST_NAME`
    - `HTTP_X_FIRST_NAME`
    The middleware assesses requests containing these headers, and (having deferred user
    authentication to the upstream service), retrieves the local Django User and logs
    the user in automatically.
    If the request path starts with one of the defined logout paths and a `HTTP_X_LOGOUT_URL`
    value is set in the response, log out the user and redirect to that URL instead.
    """

    def process_request(self, request):
        # Logout headers included with request.
        if is_logout_url(request.path) and request.META.get("HTTP_X_LOGOUT_URL"):
            logout(request)
            logout_url = request.META["HTTP_X_LOGOUT_URL"]
            if is_allowed_logout_url(logout_url):
                return http.HttpResponseRedirect(logout_url)
            logger.warning("Ignoring disallowed logout redirect URL: %s", logout_url)
            return http.HttpResponseRedirect("/")

        # Auth2 is not enabled, skip further processing.
        sso_username = request.META.get("HTTP_REMOTE_USER", "").strip()
        if not sso_username:
            # auth2 not enabled
            return

        # Auth2 is enabled. The identity headers are untrusted input, so normalise
        # them once here and use these values throughout: surrounding whitespace
        # would otherwise never compare equal to the stored values and force a
        # logout/login cycle on every request.
        sso_email = request.META.get("HTTP_X_EMAIL", "").strip()

        # Security check: if the logged-in request user's email does not match the email
        # returned from Auth2, invalidate the current request session and force a new session
        # using the returned SSO values. The comparison ignores case and surrounding whitespace.
        if request.user.is_authenticated and (request.user.email or "").strip().lower() != sso_email.lower():
            logout(request)

        # check whether request is authenticated by auth2
        if not sso_email:
            # request is not authenticated by auth2, attach the guest to request object
            request.user = guest
            return

        # Request is authenticated by auth2
        # Request user is not authenticated locally: obtain user attributes from the request.META dict
        # returned by SSO.
        if not request.user.is_authenticated:
            attributes = {"username": ""}

            for key, meta_value in attributemap.items():
                if meta_value in request.META:
                    attributes[key] = request.META[meta_value]

            # Use the normalised identity values rather than the raw headers.
            attributes["username"] = sso_username
            attributes["email"] = sso_email

            # Sanitise first_name and last_name values, because end-users have control over these
            # values and could conceivably inject malicious values into them (e.g. a XSS attack).
            if "first_name" in attributes:
                attributes["first_name"] = strip_tags(attributes["first_name"])
                attributes["first_name"] = str(escape(attributes["first_name"]))
            if "last_name" in attributes:
                attributes["last_name"] = strip_tags(attributes["last_name"])
                attributes["last_name"] = str(escape(attributes["last_name"]))

            if f_check_email_suffix and not f_check_email_suffix(attributes["email"].lower()):
                return http.HttpResponseForbidden()

            # Check for an existing User instance.
            # try to find the user with email address
            user = User.objects.filter(email__iexact=attributes["email"]).first()

            # if not found, try to find the user with username
            if not user and User.__name__ != "EmailUser":
                user = User.objects.filter(username__iexact=attributes["username"]).first()

            # if still not found, create an empty user instance
            if not user:
                user = User(last_login=timezone.localtime())

            # Set the user's details from the supplied information.
            user_has_changed = False
            for attr, value in attributes.items():
                if getattr(user, attr) != value:
                    setattr(user, attr, value)
                    user_has_changed = True
            if user_has_changed:
                user.save()

            user.backend = "django.contrib.auth.backends.ModelBackend"

            # Log the user in.
            login(request, user)

        # Synchronize Auth2 user groups if enabled.
        if ENABLE_AUTH2_GROUPS and "HTTP_X_GROUPS" in request.META:
            groups = request.META["HTTP_X_GROUPS"] or None
            if groups != request.session.get("usergroups"):
                if request.user.is_authenticated:
                    sync_usergroups(request.user, groups)
                request.session["usergroups"] = groups
