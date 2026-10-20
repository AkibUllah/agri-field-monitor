"""Run the AWD rule check once; schedule it (cron / compose) every few hours."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.alerts.awd import run_awd_check


class Command(BaseCommand):
    help = "Evaluate AWD rules for all active fields and open/resolve alerts."

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        result = run_awd_check()
        self.stdout.write(
            f"checked {result.fields_checked} fields: opened {result.opened}, "
            f"resolved {result.resolved}, unchanged {result.unchanged}"
        )
