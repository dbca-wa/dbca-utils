import importlib
import os
import random
import string
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.test.client import Client
from django.urls import reverse

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


class AllowedEmailSuffixTest(TestCase):
    """Test the ALLOWED_EMAIL_SUFFIXES configuration of SSOLoginMiddleware."""

    client = Client()

    def setUp(self):
        import dbca_utils.middleware as middleware

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
