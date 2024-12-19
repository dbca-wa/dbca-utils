from django.urls import path

from .views import TestModelListView

urlpatterns = [
    path("test-models/", TestModelListView.as_view(), name="test_model_list"),
]
