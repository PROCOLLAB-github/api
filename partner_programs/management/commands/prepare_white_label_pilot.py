"""Подготовить только изолированное демо с синтетическими участниками."""

import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    def handle(self, *args, **options):
        if not getattr(settings, "PILOT_LOCAL_FILES", False):
            raise CommandError("Нужен изолированный профиль procollab.settings_pilot.")
        password = os.environ.get("PILOT_ACCOUNT_PASSWORD", "")
        if len(password) < 16:
            raise CommandError("Задайте PILOT_ACCOUNT_PASSWORD длиной от 16 символов.")
        call_command("seed_white_label_demo", password=password, stdout=self.stdout)
