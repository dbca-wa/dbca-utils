from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.list import ListView

from dbca_utils.utils import env

from .models import TestModel


class TestModelListView(LoginRequiredMixin, ListView):
    model = TestModel
    template_name = "tests/test_model_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["TITLE"] = env("TEST_ENVIRONMENT_VAR")
        return context
