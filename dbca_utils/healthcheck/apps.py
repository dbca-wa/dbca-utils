import atexit

from django.apps import AppConfig
from . import healthcheck


class HealthcheckConfig(AppConfig):
    name = 'healthcheck'

    def ready(self):
        # Prevent running initialization code twice during local development
        if healthcheck.HEALTHCHECK_ENABLED:
            healthcheck.register_healtcheckurls()


