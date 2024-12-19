from django.db import models

from dbca_utils.models import ActiveMixin, ActiveMixinManager, AuditMixin


class TestModel(ActiveMixin, AuditMixin):
    name = models.CharField(max_length=64)
    objects = ActiveMixinManager()

    def __str__(self):
        return self.name
