import os
import random
import string

from django.contrib.auth.models import User
from django.test import TestCase
from django.test.client import Client
from django.urls import reverse

from .models import TestModel

# Define an environment variable for testing.
letters = string.ascii_letters
TEST_VAR = "".join(random.choice(letters) for _ in range(128))
TEST_NAME = "".join(random.choice(letters) for _ in range(128))
os.environ["TEST_ENVIRONMENT_VAR"] = TEST_VAR


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
