"""Write the weekly AWD report to a CSV or XLSX file, e.g. from cron every Monday morning."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.alerts.export import export_filename, to_csv, to_xlsx
from apps.alerts.reports import GROUP_FIELDS, monday_of, weekly_report


class Command(BaseCommand):
    help = "Export the weekly AWD report (last full week by default) to CSV or XLSX."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--format", choices=["csv", "xlsx"], default="xlsx")
        parser.add_argument("--group-by", choices=sorted(GROUP_FIELDS), default="upazila")
        parser.add_argument("--week-start", help="YYYY-MM-DD; default: Monday of last week")
        parser.add_argument("--upazila", default="")
        parser.add_argument("--union", dest="union_name", default="")
        parser.add_argument(
            "--output",
            "-o",
            help="file or directory to write; default: a dated file name in the current directory",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        if options["week_start"]:
            try:
                week_start = date.fromisoformat(options["week_start"])
            except ValueError as exc:
                raise CommandError(f"--week-start must be YYYY-MM-DD, got {options['week_start']!r}") from exc
        else:
            week_start = monday_of(timezone.localdate() - timedelta(days=7))

        fmt, group_by = options["format"], options["group_by"]
        rows = weekly_report(
            week_start=week_start,
            group_by=group_by,
            upazila=options["upazila"] or None,
            union_name=options["union_name"] or None,
        )
        if fmt == "csv":
            body = to_csv(rows)
        else:
            filters = {"upazila": options["upazila"], "union": options["union_name"]}
            body = to_xlsx(rows, week_start, group_by, filters=filters)

        default_name = export_filename(week_start, group_by, fmt)
        target = Path(options["output"]) if options["output"] else Path(default_name)
        if target.is_dir():
            target = target / default_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        self.stdout.write(f"wrote {len(rows)} rows ({fmt}, by {group_by}, week of {week_start}) to {target}")
