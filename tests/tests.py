import importlib
import json
import os
import random
import signal
import string
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.test.client import Client
from django.urls import reverse

from dbca_utils.healthcheck import healthcheck as healthcheck_module
from dbca_utils.healthcheck.healthcheck import _find_oldest_workload, item_version, populate_summary_data
from dbca_utils.middleware import is_logout_url
from dbca_utils.utils import env

from .models import TestModel

# Define an environment variable for testing.
letters = string.ascii_letters
TEST_VAR = "".join(random.choice(letters) for _ in range(128))
TEST_NAME = "".join(random.choice(letters) for _ in range(128))
os.environ["TEST_ENVIRONMENT_VAR"] = TEST_VAR

os.environ["TEST_STR"] = "string"
os.environ["TEST_INT"] = "42"
os.environ["TEST_FLOAT"] = "3.14159"
os.environ["TEST_LIST"] = "[1,2,3,4,5]"
os.environ["TEST_TUPLE"] = "('a', 'b', 'c')"
os.environ["TEST_BOOL"] = "False"


class UtilsTest(TestCase):
    def test_env_returns_str(self):
        test_str = env("TEST_STR")
        self.assertTrue(isinstance(test_str, str))

    def test_env_returns_int(self):
        test_int = env("TEST_INT")
        self.assertTrue(isinstance(test_int, int))

    def test_env_returns_float(self):
        test_float = env("TEST_FLOAT")
        self.assertTrue(isinstance(test_float, float))

    def test_env_returns_list(self):
        test_list = env("TEST_LIST")
        self.assertTrue(isinstance(test_list, list))

    def test_env_returns_tuple(self):
        test_tuple = env("TEST_TUPLE")
        self.assertTrue(isinstance(test_tuple, tuple))

    def test_env_returns_bool(self):
        test_bool = env("TEST_BOOL")
        self.assertTrue(isinstance(test_bool, bool))

    def test_env_returns_default(self):
        test_str = env("TEST_MISSING", "foo")
        self.assertTrue(isinstance(test_str, str))

    def test_env_missing_not_required_no_default(self):
        test_env = env("TEST_MISSING")
        self.assertIsNone(test_env)

    def test_env_required_throws_exception(self):
        with pytest.raises(Exception):
            env("TEST_MISSING_REQUIRED", required=True)

    def test_env_returns_other_as_str(self):
        test_str = env("TEST_FLOAT", value_type=str)
        self.assertTrue(isinstance(test_str, str))

    def test_env_empty_int_returns_default(self):
        """An empty numeric env var falls back to the default (regression: ValueError)."""
        with patch.dict(os.environ, {"TEST_EMPTY_INT": ""}):
            self.assertEqual(env("TEST_EMPTY_INT", default=0), 0)

    def test_env_empty_float_returns_default(self):
        with patch.dict(os.environ, {"TEST_EMPTY_FLOAT": ""}):
            self.assertEqual(env("TEST_EMPTY_FLOAT", default=1.5), 1.5)

    def test_env_whitespace_int_returns_default(self):
        with patch.dict(os.environ, {"TEST_EMPTY_INT": "   "}):
            self.assertEqual(env("TEST_EMPTY_INT", default=7), 7)

    def test_env_empty_int_without_default_returns_none(self):
        with patch.dict(os.environ, {"TEST_EMPTY_INT": ""}):
            self.assertIsNone(env("TEST_EMPTY_INT", value_type=int))

    def test_env_empty_required_int_raises(self):
        with patch.dict(os.environ, {"TEST_EMPTY_INT": ""}), pytest.raises(Exception):
            env("TEST_EMPTY_INT", value_type=int, required=True)

    def test_env_empty_str_still_returns_empty_string(self):
        """Empty strings remain valid str values (no change to existing behaviour)."""
        with patch.dict(os.environ, {"TEST_EMPTY_STR": ""}):
            self.assertEqual(env("TEST_EMPTY_STR", value_type=str), "")


class ModelTest(TestCase):
    client = Client()
    model = TestModel

    def setUp(self):
        self.user = User.objects.create_user(username="test", email="test@email.com", password="secret")
        self.test_model = TestModel.objects.create(name=TEST_NAME)
        self.client.login(username="test", password="secret")

    def tearDown(self):
        self.user.delete()

    def test_model_fields(self):
        """Test a model inheriting from mixins has the required fields."""
        self.assertTrue(hasattr(self.test_model, "effective_to"))
        self.assertTrue(hasattr(self.test_model, "creator"))
        self.assertTrue(hasattr(self.test_model, "modifier"))
        self.assertTrue(hasattr(self.test_model, "created"))
        self.assertTrue(hasattr(self.test_model, "modified"))

    def test_active_mixin(self):
        """Test the ActiveMixin manager methods."""
        obj_del = TestModel.objects.create(name="Deleted object")
        obj_del.delete()
        all_pks = [i.pk for i in TestModel.objects.all()]
        current_pks = [i.pk for i in TestModel.objects.current()]
        del_pks = [i.pk for i in TestModel.objects.deleted()]
        self.assertTrue(obj_del.pk in all_pks)
        self.assertFalse(obj_del.pk in current_pks)
        self.assertTrue(obj_del.pk in del_pks)
        self.assertFalse(self.test_model.pk in del_pks)

    def test_delete_with_force_false_soft_deletes(self):
        """delete(force=False) must soft delete instead of raising TypeError."""
        obj = TestModel.objects.create(name="Soft deleted object")
        obj.delete(force=False)
        self.assertIsNotNone(obj.effective_to)
        self.assertTrue(TestModel.objects.filter(pk=obj.pk).exists())
        self.assertFalse(TestModel.objects.current().filter(pk=obj.pk).exists())
        self.assertTrue(TestModel.objects.deleted().filter(pk=obj.pk).exists())

    def test_delete_with_force_true_hard_deletes(self):
        """delete(force=True) removes the row and returns Django's delete result."""
        obj = TestModel.objects.create(name="Hard deleted object")
        deleted, per_model = obj.delete(force=True)
        self.assertEqual(deleted, 1)
        self.assertEqual(per_model, {obj._meta.label: 1})
        self.assertFalse(TestModel.objects.filter(pk=obj.pk).exists())

    def test_changed_data_is_reset_after_save(self):
        """changed_data must not keep reporting changes that have been saved."""
        self.assertEqual(self.test_model.changed_data, [])
        self.test_model.name = "Updated name"
        self.assertEqual(self.test_model.changed_data, ["name"])
        self.assertTrue(self.test_model.has_changed())
        self.test_model.save()
        self.assertEqual(self.test_model.changed_data, [])
        self.assertFalse(self.test_model.has_changed())

    def test_changed_data_tracks_changes_after_creation(self):
        """A newly created object still detects later modifications."""
        obj = TestModel.objects.create(name="Created")
        self.assertEqual(obj.changed_data, [])
        obj.name = "Renamed"
        self.assertEqual(obj.changed_data, ["name"])

    def test_changed_data_ignores_modified_and_modifier(self):
        """modified and modifier are excluded from change tracking."""
        self.test_model.modifier = self.user
        self.test_model.save()
        self.assertEqual(self.test_model.changed_data, [])
        self.test_model.name = "Another name"
        self.assertEqual(self.test_model.changed_data, ["name"])
        # Clear the protected FK so tearDown can remove the user.
        self.test_model.modifier = None
        self.test_model.save()

    def test_changed_data_is_reset_after_soft_delete(self):
        """A soft delete records effective_to without leaving it marked as changed."""
        self.test_model.delete()
        self.assertTrue(self.test_model.is_deleted())
        self.assertEqual(self.test_model.changed_data, [])

    def test_changed_data_is_reset_after_refresh_from_db(self):
        """Reloading from the database re-baselines change tracking."""
        TestModel.objects.filter(pk=self.test_model.pk).update(name="Changed in db")
        self.test_model.refresh_from_db()
        self.assertEqual(self.test_model.changed_data, [])

    def test_url_request_returns_view(self):
        """Test the env() utility method works as expected."""
        url = reverse("test_model_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, TEST_VAR)
        self.assertContains(response, TEST_NAME)


class SSOLoginMiddlewareTest(TestCase):
    client = Client()

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="testuser@email.com")
        # Ensure that the client starts logged out.
        self.client.logout()

    def test_sso_login(self):
        """Test that requests having the required META headers will automatically sign in users."""
        url = reverse("test_model_list")
        response = self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")

    def test_email_case_difference_keeps_session(self):
        """Case-only email differences must not force a logout/login cycle."""
        user = User.objects.create_user(username="caseuser", email="Case.User@Email.com")
        self.client.logout()
        url = reverse("test_model_list")
        self.client.get(url, HTTP_REMOTE_USER="caseuser", HTTP_X_EMAIL="case.user@email.com")
        session_key = self.client.session.session_key
        response = self.client.get(url, HTTP_REMOTE_USER="caseuser", HTTP_X_EMAIL="case.user@email.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")
        self.assertEqual(self.client.session.session_key, session_key)
        # The SSO header email is authoritative, so the stored address follows
        # the header casing; only the session must survive the case difference.
        user.refresh_from_db()
        self.assertEqual(user.email, "case.user@email.com")

    def test_email_whitespace_keeps_session(self):
        """Whitespace around the SSO email must not force a logout/login cycle."""
        self.client.force_login(self.user)
        url = reverse("test_model_list")
        self.client.get(url, HTTP_REMOTE_USER="testuser", HTTP_X_EMAIL="  testuser@email.com  ")
        session_key = self.client.session.session_key
        response = self.client.get(url, HTTP_REMOTE_USER="testuser", HTTP_X_EMAIL="  testuser@email.com  ")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")
        self.assertEqual(self.client.session.session_key, session_key)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "testuser@email.com")

    def test_padded_identity_headers_are_trimmed(self):
        """Identity headers are trimmed before user lookup and storage."""
        url = reverse("test_model_list")
        response = self.client.get(url, HTTP_REMOTE_USER="  newuser  ", HTTP_X_EMAIL="  newuser@email.com  ")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")
        self.assertEqual(User.objects.filter(username="newuser", email="newuser@email.com").count(), 1)
        self.assertFalse(User.objects.filter(username__regex=r"^\s|\s$").exists())
        self.assertFalse(User.objects.filter(email__regex=r"^\s|\s$").exists())
        # A second identical request reuses the same account.
        self.client.get(url, HTTP_REMOTE_USER="  newuser  ", HTTP_X_EMAIL="  newuser@email.com  ")
        self.assertEqual(User.objects.filter(email="newuser@email.com").count(), 1)

    def test_whitespace_only_remote_user_is_ignored(self):
        """A whitespace-only REMOTE_USER counts as 'auth2 not enabled'."""
        url = reverse("test_model_list")
        response = self.client.get(url, HTTP_REMOTE_USER="   ", HTTP_X_EMAIL="someone@email.com")
        # The view requires login, so an ignored SSO header means a login redirect.
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response["Location"])
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(User.objects.filter(email="someone@email.com").exists())

    def test_user_properties_update(self):
        """Test that requests with relevant META headers will update user properties."""
        url = reverse("test_model_list")

        response = self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")
        user = User.objects.get(email="testuser@email.com")
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "")

        # Simulate a name change via SSO.
        self.client.logout()
        response = self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
            HTTP_X_FIRST_NAME="Test",
            HTTP_X_LAST_NAME="User",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Name: Test User")
        user = User.objects.get(email="testuser@email.com")
        self.assertEqual(user.first_name, "Test")
        self.assertEqual(user.last_name, "User")


class SSOLoginMiddlewareGroupTest(TestCase):
    client = Client()

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="testuser@email.com")
        self.client.logout()

    @patch("dbca_utils.middleware.ENABLE_AUTH2_GROUPS", True)
    def test_sso_login_creates_and_syncs_groups(self):
        """Test that SSO login creates groups and assigns them to the user."""
        url = reverse("test_model_list")
        response = self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
            HTTP_X_GROUPS="group1,group2",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")
        self.user.refresh_from_db()
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["group1", "group2"],
        )
        self.assertEqual(self.client.session.get("usergroups"), "group1,group2")

    @patch("dbca_utils.middleware.ENABLE_AUTH2_GROUPS", True)
    def test_group_sync_updates_on_header_change(self):
        """Test that group membership is updated when the HTTP_X_GROUPS header changes."""
        url = reverse("test_model_list")
        self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
            HTTP_X_GROUPS="group1,group2",
        )
        self.user.refresh_from_db()
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["group1", "group2"],
        )

        self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
            HTTP_X_GROUPS="group2,group3",
        )
        self.user.refresh_from_db()
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["group2", "group3"],
        )

    @patch("dbca_utils.middleware.ENABLE_AUTH2_GROUPS", True)
    def test_group_header_whitespace_is_trimmed(self):
        """Group names from the header are stripped and empty entries ignored."""
        url = reverse("test_model_list")
        response = self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
            HTTP_X_GROUPS=" group1 , group2 , ",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["group1", "group2"],
        )
        self.assertFalse(Group.objects.filter(name__regex=r"^\s|\s$").exists())

    @patch("dbca_utils.middleware.LOCAL_USERGROUPS", ["local_group"])
    @patch("dbca_utils.middleware.ENABLE_AUTH2_GROUPS", True)
    def test_group_sync_preserves_local_groups(self):
        """Test that groups listed in LOCAL_USERGROUPS are not removed."""
        local_group = Group.objects.create(name="local_group")
        self.user.groups.add(local_group)
        url = reverse("test_model_list")
        response = self.client.get(
            url,
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@email.com",
            HTTP_X_GROUPS="sso_group",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        group_names = sorted(self.user.groups.values_list("name", flat=True))
        self.assertEqual(group_names, ["local_group", "sso_group"])


class GroupSeparatorTest(TestCase):
    """Test the GROUP_SEPARATOR configuration of SSOLoginMiddleware."""

    client = Client()

    def setUp(self):
        from dbca_utils import middleware

        self.middleware = middleware
        self.user = User.objects.create_user(username="groupuser", email="groupuser@email.com")
        self.addCleanup(self._reload, None)

    def _reload(self, separator):
        if separator is None:
            os.environ.pop("GROUP_SEPARATOR", None)
        else:
            os.environ["GROUP_SEPARATOR"] = separator
        importlib.reload(self.middleware)

    def test_default_separator_is_comma(self):
        self._reload(None)
        self.assertEqual(self.middleware.GROUP_SEPARATOR, ",")

    def test_env_separator_is_applied(self):
        self._reload(";")
        self.assertEqual(self.middleware.GROUP_SEPARATOR, ";")

    def test_empty_separator_falls_back_to_comma(self):
        """An empty separator would make str.split() raise, so fall back to ','."""
        self._reload("")
        self.assertEqual(self.middleware.GROUP_SEPARATOR, ",")
        self.middleware.sync_usergroups(self.user, "group1,group2")
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["group1", "group2"],
        )

    def test_custom_separator_splits_and_trims(self):
        self._reload(";")
        self.middleware.sync_usergroups(self.user, " group1 ;; group2 ")
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["group1", "group2"],
        )

    def test_comma_is_not_a_separator_when_overridden(self):
        self._reload(";")
        self.middleware.sync_usergroups(self.user, "team,alpha;team,beta")
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["team,alpha", "team,beta"],
        )

    @patch("dbca_utils.middleware.ENABLE_AUTH2_GROUPS", True)
    @patch("dbca_utils.middleware.GROUP_SEPARATOR", ";")
    def test_sso_login_uses_custom_separator(self):
        """The middleware splits the X-Groups header using GROUP_SEPARATOR."""
        url = reverse("test_model_list")
        response = self.client.get(
            url,
            HTTP_REMOTE_USER="groupuser",
            HTTP_X_EMAIL="groupuser@email.com",
            HTTP_X_GROUPS="alpha; beta",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")
        self.user.refresh_from_db()
        self.assertEqual(
            sorted(self.user.groups.values_list("name", flat=True)),
            ["alpha", "beta"],
        )


class AllowedEmailSuffixTest(TestCase):
    """Test the ALLOWED_EMAIL_SUFFIXES configuration of SSOLoginMiddleware."""

    client = Client()

    def setUp(self):
        from dbca_utils import middleware

        self.middleware = middleware
        self.addCleanup(self._reload_without_suffixes)
        self.client.logout()

    def _reload_without_suffixes(self):
        os.environ.pop("ALLOWED_EMAIL_SUFFIXES", None)
        importlib.reload(self.middleware)

    def _reload_with_suffixes(self, suffixes):
        with patch.dict(os.environ, {"ALLOWED_EMAIL_SUFFIXES": repr(suffixes)}):
            return importlib.reload(self.middleware)

    def test_single_suffix(self):
        """A single suffix restricts logins to that email domain."""
        middleware = self._reload_with_suffixes(["@dbca.wa.gov.au"])
        self.assertTrue(middleware.f_check_email_suffix("user@dbca.wa.gov.au"))
        self.assertFalse(middleware.f_check_email_suffix("user@example.com"))

    def test_multiple_suffixes(self):
        """Multiple suffixes must be accepted (regression: NameError on import)."""
        middleware = self._reload_with_suffixes(["@dbca.wa.gov.au", "@dpaw.wa.gov.au"])
        self.assertTrue(middleware.f_check_email_suffix("user@dbca.wa.gov.au"))
        self.assertTrue(middleware.f_check_email_suffix("user@dpaw.wa.gov.au"))
        self.assertFalse(middleware.f_check_email_suffix("user@example.com"))

    def test_no_suffixes_disables_check(self):
        """An empty suffix list disables the email domain check."""
        middleware = self._reload_with_suffixes([])
        self.assertIsNone(middleware.f_check_email_suffix)

    def test_multiple_suffixes_allows_login(self):
        """A user with an allowed email suffix is logged in."""
        self._reload_with_suffixes(["@dbca.wa.gov.au", "@dpaw.wa.gov.au"])
        response = self.client.get(
            reverse("test_model_list"),
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@dpaw.wa.gov.au",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authenticated: True")

    def test_multiple_suffixes_forbids_login(self):
        """A user with a disallowed email suffix is rejected and not created."""
        self._reload_with_suffixes(["@dbca.wa.gov.au", "@dpaw.wa.gov.au"])
        response = self.client.get(
            reverse("test_model_list"),
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@example.com",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="testuser").exists())


class SSOLoginMiddlewareLogoutTest(TestCase):
    """Test the logout redirect handling of SSOLoginMiddleware."""

    client = Client()

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="testuser@dbca.wa.gov.au")
        self.client.force_login(self.user)

    def _logout_request(self, logout_url):
        return self.client.get(
            "/logout",
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@dbca.wa.gov.au",
            HTTP_X_LOGOUT_URL=logout_url,
        )

    def test_redirects_to_allowed_dbca_hosts(self):
        """HTTPS URLs on dbca.wa.gov.au and its subdomains are allowed."""
        for url in (
            "https://app.dbca.wa.gov.au/sso/logout",
            "https://dbca.wa.gov.au/logout",
            "https://APP.DBCA.WA.GOV.AU/logout",
            "https://app.dbca.wa.gov.au:8443/logout",
        ):
            with self.subTest(url=url):
                response = self._logout_request(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], url)

    def test_redirects_to_relative_url(self):
        """Relative logout URLs stay on the current host and are allowed."""
        response = self._logout_request("/sso/logout")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/sso/logout")

    def test_rejects_disallowed_urls(self):
        """External, plain HTTP and lookalike hosts are not used for redirects."""
        for url in (
            "https://evil.example/phish",
            "https://dbca.wa.gov.au.evil.example/",
            "https://evil-dbca.wa.gov.au/",
            "https://dbca.wa.gov.au@evil.example/",
            "//evil.example/phish",
            "http://app.dbca.wa.gov.au/logout",
            "javascript:alert(1)",
        ):
            with self.subTest(url=url):
                response = self._logout_request(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/")

    def test_logout_clears_session(self):
        """The user is logged out regardless of the redirect target."""
        self._logout_request("https://app.dbca.wa.gov.au/sso/logout")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_rejected_redirect_still_logs_out(self):
        """A disallowed redirect does not prevent the logout."""
        self._logout_request("https://evil.example/phish")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_paths_sharing_a_logout_prefix_do_not_log_out(self):
        """Only exact logout paths trigger the logout flow."""
        for path in ("/logout-confirm", "/logoutx", "/admin/logoutfoo", "/logout/success", "/ledger/logout-something"):
            with self.subTest(path=path):
                self.client.force_login(self.user)
                response = self.client.get(
                    path,
                    HTTP_REMOTE_USER="testuser",
                    HTTP_X_EMAIL="testuser@dbca.wa.gov.au",
                    HTTP_X_LOGOUT_URL="https://app.dbca.wa.gov.au/sso/logout",
                )
                self.assertEqual(response.status_code, 404)
                self.assertIn("_auth_user_id", self.client.session)

    def test_logout_path_with_trailing_slash_logs_out(self):
        """A trailing slash on a configured logout path still matches."""
        response = self.client.get(
            "/logout/",
            HTTP_REMOTE_USER="testuser",
            HTTP_X_EMAIL="testuser@dbca.wa.gov.au",
            HTTP_X_LOGOUT_URL="https://app.dbca.wa.gov.au/sso/logout",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://app.dbca.wa.gov.au/sso/logout")
        self.assertNotIn("_auth_user_id", self.client.session)


class LogoutUrlConfigTest(TestCase):
    """Test LOGOUT_URLS matching and configuration parsing."""

    @patch("dbca_utils.middleware.LOGOUT_URLS", ["/logout", "/admin/logout"])
    def test_matches_exact_paths(self):
        for path in ("/logout", "/logout/", "/admin/logout", "/admin/logout/"):
            with self.subTest(path=path):
                self.assertTrue(is_logout_url(path))

    @patch("dbca_utils.middleware.LOGOUT_URLS", ["/logout", "/admin/logout"])
    def test_rejects_prefix_and_subpath_matches(self):
        for path in (
            "/logout-confirm",
            "/logoutx",
            "/admin/logoutfoo",
            "/logout/success",
            "/admin/logout/extra",
            "/",
            "",
            None,
        ):
            with self.subTest(path=path):
                self.assertFalse(is_logout_url(path))

    def test_single_string_logout_urls_is_supported(self):
        """LOGOUT_URLS may be configured as a single string, not just a list."""
        from dbca_utils import middleware

        self.addCleanup(self._reload, None)
        self._reload("/signout")
        self.assertEqual(middleware.LOGOUT_URLS, ["/signout"])
        self.assertTrue(middleware.is_logout_url("/signout"))
        self.assertFalse(middleware.is_logout_url("/signout-other"))

    def _reload(self, value):
        from dbca_utils import middleware

        if value is None:
            os.environ.pop("LOGOUT_URLS", None)
        else:
            os.environ["LOGOUT_URLS"] = value
        importlib.reload(middleware)


def _healthcheck_payload(start_time, cpu, pmemory, vmemory, processes=1, hostname=None):
    """Build a minimal workload health payload for summary tests."""
    payload = {
        "resources": {
            "start_time": start_time,
            "processes": processes,
            "cpu_total": cpu,
            "cpu_min": cpu,
            "cpu_max": cpu,
            "pmemory_total": pmemory,
            "pmemory_min": pmemory,
            "pmemory_max": pmemory,
            "vmemory_total": vmemory,
            "vmemory_min": vmemory,
            "vmemory_max": vmemory,
        }
    }
    if hostname:
        payload["hostname"] = hostname
    return payload


class HealthcheckSummaryTest(TestCase):
    """Test populate_summary_data aggregation of workload health data."""

    def test_summary_totals(self):
        """Totals and min/max are aggregated across workloads (cpu counted once)."""
        datas = {
            "workload0": _healthcheck_payload("2026-01-01T00:00:00", 10, 100, 200, processes=2),
            "workload1": _healthcheck_payload("2026-01-02T00:00:00", 20, 300, 400, processes=3),
        }
        populate_summary_data(datas)
        summary = datas["summary"]
        self.assertEqual(summary["cpu_total"], 30)
        self.assertEqual(summary["cpu_min"], 10)
        self.assertEqual(summary["cpu_max"], 20)
        self.assertEqual(summary["pmemory_total"], 400)
        self.assertEqual(summary["pmemory_min"], 100)
        self.assertEqual(summary["pmemory_max"], 300)
        self.assertEqual(summary["vmemory_total"], 600)
        self.assertEqual(summary["processes_total"], 5)
        self.assertEqual(summary["workloads_running"], 2)
        self.assertEqual(summary["workloads_failed"], 0)

    def test_summary_ignores_failed_workloads(self):
        """Failed workloads are counted but excluded from the totals."""
        datas = {
            "workload0": _healthcheck_payload("2026-01-01T00:00:00", 10, 100, 200),
            "workload1": "workload1: connection refused",
        }
        populate_summary_data(datas)
        summary = datas["summary"]
        self.assertEqual(summary["cpu_total"], 10)
        self.assertEqual(summary["pmemory_total"], 100)
        self.assertEqual(summary["vmemory_total"], 200)
        self.assertEqual(summary["processes_total"], 1)
        self.assertEqual(summary["workloads_running"], 1)
        self.assertEqual(summary["workloads_failed"], 1)

    def test_summary_latest_workload(self):
        """The workload with the most recent start_time is reported."""
        datas = {
            "workload0": _healthcheck_payload("2026-01-02T00:00:00", 1, 1, 1, hostname="pod-a"),
            "workload1": _healthcheck_payload("2026-01-01T00:00:00", 1, 1, 1, hostname="pod-b"),
        }
        populate_summary_data(datas)
        self.assertEqual(
            datas["summary"]["latest_workload"],
            {"hostname": "pod-a", "start_time": "2026-01-02T00:00:00"},
        )


class HealthcheckWorkloadSelectionTest(TestCase):
    """Test selection of the assigned workload a spare server should replace."""

    def test_skips_assigned_server_without_health_data(self):
        """An unreachable assigned server must not raise KeyError (regression)."""
        datas = {"server-a": (200, _healthcheck_payload("2026-01-02T00:00:00", 1, 1, 1))}
        assigned = {
            item_version: 1,
            "workload0": "server-a",
            "workload1": "server-gone",
        }
        oldworkload = _find_oldest_workload(assigned, datas)
        self.assertEqual(oldworkload[0], "workload0")
        self.assertEqual(oldworkload[1], "server-a")

    def test_returns_none_when_no_assigned_server_has_data(self):
        assigned = {item_version: 1, "workload0": "server-gone"}
        self.assertIsNone(_find_oldest_workload(assigned, {}))

    def test_prefers_unhealthy_workload(self):
        datas = {
            "server-a": (200, _healthcheck_payload("2026-01-02T00:00:00", 1, 1, 1)),
            "server-b": (503, "unavailable"),
        }
        assigned = {
            item_version: 1,
            "workload0": "server-a",
            "workload1": "server-b",
            "workload2": "server-gone",
        }
        oldworkload = _find_oldest_workload(assigned, datas)
        self.assertEqual(oldworkload[0], "workload1")
        self.assertEqual(oldworkload[1], "server-b")

    def test_prefers_oldest_workload_when_all_healthy(self):
        datas = {
            "server-a": (200, _healthcheck_payload("2026-01-02T00:00:00", 1, 1, 1)),
            "server-b": (200, _healthcheck_payload("2026-01-01T00:00:00", 1, 1, 1)),
        }
        assigned = {item_version: 1, "workload0": "server-a", "workload1": "server-b"}
        oldworkload = _find_oldest_workload(assigned, datas)
        self.assertEqual(oldworkload[0], "workload1")
        self.assertEqual(oldworkload[1], "server-b")


class HealthcheckDeploymentViewTest(TestCase):
    """End-to-end checks for the fixed-workload deployment healthdata view."""

    def setUp(self):
        self._reload_module()

    def _reload_module(self, workloads=2):
        env_vars = {"WORKLOADS": str(workloads), "WORKLOAD_DEPLOYMENT": "true", "HEALTHCHECK_ENABLED": "true"}
        with patch.dict(os.environ, env_vars):
            self.hc = importlib.reload(healthcheck_module)
        self.hc.cache = cache
        cache.clear()

    def tearDown(self):
        cache.clear()
        # Restore the module's default (dynamic workloads) configuration.
        importlib.reload(healthcheck_module)

    def test_unreachable_assigned_server_is_reported_as_offline(self):
        assigned = {
            self.hc.item_version: 1,
            "workload0": "server-a",
            "workload1": "server-gone",
        }
        cache.set(self.hc.key_assignedworkloads, assigned, timeout=None)
        workloads = {"server-a": ["10.0.0.1", 8080, 0]}
        servers_res = {"server-a": (200, _healthcheck_payload("2026-01-01T00:00:00", 1, 1, 1))}
        request = RequestFactory().get("/healthcheck/healthdata")
        with patch.object(self.hc, "harvest_healthdata", return_value=(workloads, servers_res)):
            response = self.hc.healthdata_view(request)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result["workload0"]["resources"]["cpu_total"], 1)
        self.assertIn("server-gone", result["workload1"])
        self.assertIn("offline host", result["workload1"])

    def test_stale_workload_assignment_is_removed_and_saved(self):
        """Assignments for workloads that no longer exist are dropped and persisted."""
        assigned = {
            self.hc.item_version: 1,
            "workload0": "server-a",
            "workload9": "server-b",
        }
        cache.set(self.hc.key_assignedworkloads, assigned, timeout=None)
        workloads = {"server-a": ["10.0.0.1", 8080, 0], "server-b": ["10.0.0.2", 8080, 0]}
        servers_res = {
            "server-a": (200, _healthcheck_payload("2026-01-01T00:00:00", 1, 1, 1)),
            "server-b": (200, _healthcheck_payload("2026-01-02T00:00:00", 2, 2, 2)),
        }
        request = RequestFactory().get("/healthcheck/healthdata")
        with patch.object(self.hc, "harvest_healthdata", return_value=(workloads, servers_res)):
            response = self.hc.healthdata_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("workload9", json.loads(response.content))
        saved = cache.get(self.hc.key_assignedworkloads)
        self.assertNotIn("workload9", saved)
        self.assertEqual(saved["workload1"], "server-b")

    @pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM is not available on this platform")
    def test_duplicate_assignment_does_not_hang(self):
        """Two workloads assigned to one server must not spin the failover loop."""
        self._reload_module(workloads=3)
        assigned = {
            self.hc.item_version: 1,
            "workload0": "server-a",
            "workload1": "server-a",
            "workload2": "server-gone",
        }
        cache.set(self.hc.key_assignedworkloads, assigned, timeout=None)
        workloads = {name: ["10.0.0.1", 8080, 0] for name in ("server-a", "server-x", "server-y")}
        servers_res = {
            "server-a": (200, _healthcheck_payload("2026-01-02T00:00:00", 1, 1, 1)),
            "server-x": (200, _healthcheck_payload("2026-01-01T00:00:00", 2, 2, 2)),
            "server-y": (200, _healthcheck_payload("2026-01-03T00:00:00", 3, 3, 3)),
        }
        request = RequestFactory().get("/healthcheck/healthdata")

        def timeout(signum, frame):
            raise TimeoutError("healthdata_view did not terminate")

        previous_handler = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(5)
        try:
            with patch.object(self.hc, "harvest_healthdata", return_value=(workloads, servers_res)):
                response = self.hc.healthdata_view(request)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)

        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result["workload0"]["resources"]["cpu_total"], 1)
        self.assertEqual(result["workload1"]["resources"]["cpu_total"], 1)
        self.assertEqual(result["workload2"]["resources"]["cpu_total"], 3)

    def test_save_assignedworkloads_handles_missing_version(self):
        """A cached mapping without __version__ must not raise KeyError."""
        cache.set(self.hc.key_assignedworkloads, {"workload0": "server-a"}, timeout=None)
        self.hc.save_assignedworkloads({"workload0": "server-b"})
        saved = cache.get(self.hc.key_assignedworkloads)
        self.assertEqual(saved["workload0"], "server-b")
        self.assertEqual(saved[self.hc.item_version], 1)

    def test_save_workloads_handles_missing_version(self):
        """A cached workloads payload without __version__ must not raise KeyError."""
        cache.set(self.hc.key_workloads, {"server-a": [["10.0.0.1", 8080], "secret", 0]}, timeout=None)
        self.hc.save_workloads({"server-b": [["10.0.0.2", 8080], "secret2", 0]})
        saved = cache.get(self.hc.key_workloads)
        self.assertEqual(saved[self.hc.item_version], 1)
