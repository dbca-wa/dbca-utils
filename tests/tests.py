import os
import random
import string

import pytest
from django.contrib.auth.models import User
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


class TestUtils(TestCase):
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


class TestModelTests(TestCase):
    client = Client()
    model = TestModel

    def setUp(self):
        self.user = User.objects.create_user(
            username="test", email="test@email.com", password="secret"
        )
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
