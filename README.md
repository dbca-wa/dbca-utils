# Overview

DBCA Django utility classes and functions.

# SSO Login Middleware

This will automatically login and create users using headers from an upstream proxy (REMOTE_USER and some others).
The logout view will redirect to a separate logout page which clears the SSO session.

## Usage

Add `dbca_utils.middleware.SSOLoginMiddleware` to `settings.MIDDLEWARE` (after both of
`django.contrib.sessions.middleware.SessionMiddleware` and
`django.contrib.auth.middleware.AuthenticationMiddleware`.
Ensure that `AUTHENTICATION_BACKENDS` contains `django.contrib.auth.backends.ModelBackend`,
as this middleware depends on it for retrieving the logged in user for a session.
Note that the middleware will still work without it, but will reauthenticate the session
on every request, and `request.user.is_authenticated` won't work properly/will be false.

Example:

```
MIDDLEWARE = [
    ...,
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'dbca_utils.middleware.SSOLoginMiddleware'
    ...,
]
```

# Audit model mixin

``AuditMixin`` is an extension of ``Django.db.model.Model`` that adds a number of additional fields:

 * creator - FK to ``AUTH_USER_MODEL``, used to record the object creator
 * modifier - FK to ``AUTH_USER_MODEL``, used to record who the object was last modified by
 * created - a timestamp that is set on initial object save
 * modified - an auto-updating timestamp (on each object save)
