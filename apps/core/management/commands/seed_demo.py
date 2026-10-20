"""Seed a realistic demo dataset: Boro-season AWD fields in Rajshahi and Bogura districts."""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.alerts.awd import run_awd_check
from apps.farms.models import Farmer, Field, Season
from apps.monitoring.models import FieldVisit, IrrigationEvent, Pipe, WaterLevelReading

# (district, upazila, union, village, approx lat, approx lng)
LOCATIONS = [
    ("Rajshahi", "Paba", "Haripur", "Nowdapara", 24.395, 88.585),
    ("Rajshahi", "Paba", "Damkura", "Damkura Hat", 24.420, 88.520),
    ("Rajshahi", "Godagari", "Rishikul", "Kakonhat", 24.515, 88.395),
    ("Rajshahi", "Godagari", "Deopara", "Basudebpur", 24.455, 88.335),
    ("Rajshahi", "Tanore", "Kalma", "Kalma Bazar", 24.605, 88.545),
    ("Bogura", "Sherpur", "Khanpur", "Khanpur", 24.655, 89.405),
    ("Bogura", "Sherpur", "Kusumbi", "Kusumbi", 24.690, 89.445),
    ("Bogura", "Shibganj", "Mokamtala", "Mokamtala", 24.995, 89.315),
    ("Bogura", "Shibganj", "Pirab", "Pirab", 25.040, 89.350),
    ("Bogura", "Dhunat", "Elangi", "Elangi", 24.690, 89.540),
]

FARMERS = [
    ("Abdul Karim", "01711000101"),
    ("Rafiqul Islam", "01811000102"),
    ("Mst. Rokeya Begum", "01911000103"),
    ("Shahidul Haque", "01611000104"),
    ("Jahanara Khatun", "01511000105"),
    ("Monirul Islam", "01311000106"),
    ("Abdur Rahman", "01711000107"),
    ("Nazma Begum", "01811000108"),
    ("Mofizul Haque", "01911000109"),
    ("Shahanaj Parvin", "01411000110"),
]

VARIETIES = ["BRRI dhan28", "BRRI dhan29", "BRRI dhan58", "BRRI dhan89", "Binadhan-10"]


def quad(rng: random.Random, lat: float, lng: float, side_m: float) -> list[list[float]]:
    """A slightly irregular quadrilateral of roughly ``side_m`` metres around (lat, lng)."""
    dlat = side_m / 111_320
    dlng = side_m / (111_320 * 0.913)  # cos(24.5 deg)
    jitter = lambda: rng.uniform(-0.08, 0.08)  # noqa: E731
    return [
        [round(lat + dlat * (0.5 + jitter()), 6), round(lng - dlng * (0.5 + jitter()), 6)],
        [round(lat + dlat * (0.5 + jitter()), 6), round(lng + dlng * (0.5 + jitter()), 6)],
        [round(lat - dlat * (0.5 + jitter()), 6), round(lng + dlng * (0.5 + jitter()), 6)],
        [round(lat - dlat * (0.5 + jitter()), 6), round(lng - dlng * (0.5 + jitter()), 6)],
    ]


class Command(BaseCommand):
    help = "Create demo farmers, fields, pipes, 3 weeks of readings, irrigation logs, visits and alerts."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--days", type=int, default=21, help="Days of reading history")
        parser.add_argument("--flush", action="store_true", help="Delete existing domain data first")

    @transaction.atomic
    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        rng = random.Random(options["seed"])
        days = options["days"]
        if options["flush"]:
            Farmer.objects.all().delete()

        user_model = get_user_model()
        agent, created = user_model.objects.get_or_create(
            username="agent", defaults={"first_name": "Field", "last_name": "Agent", "is_staff": True}
        )
        if created:
            agent.set_password("agent1234")  # demo credentials, printed below
            agent.save()

        now = timezone.now()
        today = timezone.localdate()
        fields: list[Field] = []
        for (name, phone), loc in zip(FARMERS, LOCATIONS, strict=True):
            district, upazila, union, village, lat, lng = loc
            farmer, _ = Farmer.objects.update_or_create(
                phone=phone,
                defaults={
                    "name": name,
                    "nid": str(rng.randint(10**9, 10**10 - 1)),
                    "village": village,
                    "union_name": union,
                    "upazila": upazila,
                    "district": district,
                },
            )
            for n in range(rng.choice([1, 1, 2])):
                side = rng.uniform(35, 80)
                f_lat = lat + rng.uniform(-0.01, 0.01)
                f_lng = lng + rng.uniform(-0.01, 0.01)
                field, _ = Field.objects.update_or_create(
                    farmer=farmer,
                    name=f"{village} plot {n + 1}",
                    defaults={"crop": Field.Crop.BORO, "polygon": quad(rng, f_lat, f_lng, side)},
                )
                fields.append(field)
                transplanted = today - timedelta(days=rng.randint(30, 50))
                Season.objects.update_or_create(
                    field=field,
                    transplanted_on=transplanted,
                    defaults={
                        "crop": Field.Crop.BORO,
                        "variety": rng.choice(VARIETIES),
                        "awd_start_on": transplanted + timedelta(days=14),
                        "awd_end_on": transplanted + timedelta(days=75),
                        "expected_harvest_on": transplanted + timedelta(days=110),
                        "is_active": True,
                    },
                )

        # Scenario flags so the demo shows every alert kind:
        due_field = fields[2]  # left drying -> IRRIGATION_DUE
        silent_field = fields[5]  # no readings for a week -> SENSOR_SILENT
        flooded_field = fields[7]  # over-irrigated -> OVERFLOW

        readings = 0
        for idx, field in enumerate(fields):
            pipe, _ = Pipe.objects.update_or_create(
                code=f"{field.upazila[:3].upper()}-{field.id:03d}-A",
                defaults={
                    "field": field,
                    "depth_cm": 25,
                    "installed_on": today - timedelta(days=days + 5),
                    "device_id": f"awd-node-{field.id:03d}" if idx % 3 == 0 else "",
                },
            )
            pipe.readings.all().delete()
            field.irrigation_events.all().delete()
            field.visits.all().delete()
            field.alerts.all().delete()

            level = Decimal("5.0")
            drop_per_day = Decimal(str(round(rng.uniform(1.6, 2.6), 1)))
            pending_irrigation = False
            for d in range(days, -1, -1):
                day = now - timedelta(days=d)
                if field is silent_field and d < 7:
                    continue
                if field is due_field and d == 5:
                    # Farmer away: the level reaches the threshold and keeps dropping.
                    level = Decimal(field.awd_threshold_cm) + Decimal("0.5")
                for hour in (7, 16) if pipe.device_id else (8,):
                    at = day.replace(hour=hour, minute=rng.randint(0, 59), second=0, microsecond=0)
                    noise = Decimal(str(round(rng.uniform(-0.4, 0.4), 1)))
                    WaterLevelReading.objects.create(
                        pipe=pipe,
                        level_cm=max(Decimal("-40"), min(Decimal("30"), level + noise)),
                        source=WaterLevelReading.Source.DEVICE
                        if pipe.device_id
                        else WaterLevelReading.Source.MANUAL,
                        recorded_at=at,
                        recorded_by=None if pipe.device_id else agent,
                    )
                    readings += 1
                level -= drop_per_day
                at_threshold = level <= Decimal(field.awd_threshold_cm)
                # Farmers do not always pump the same day the tube shows -15 cm: ~40% of the
                # time the irrigation lands a day late, which is what the report counts as
                # "field-days below threshold".
                should_irrigate = at_threshold and (pending_irrigation or rng.random() < 0.6)
                pending_irrigation = at_threshold and not should_irrigate
                if field is due_field and d <= 5:
                    should_irrigate = False
                if should_irrigate:
                    started = day.replace(hour=18, minute=0, second=0, microsecond=0)
                    IrrigationEvent.objects.create(
                        field=field,
                        started_at=started,
                        ended_at=started + timedelta(hours=rng.choice([2, 3, 4])),
                        method=IrrigationEvent.Method.PUMP,
                        water_mm=Decimal(str(rng.choice([45, 50, 55, 60]))),
                        logged_by=agent,
                    )
                    level = Decimal("20.0") if (field is flooded_field and d == 0) else Decimal("5.0")
            if field is flooded_field:
                WaterLevelReading.objects.create(
                    pipe=pipe,
                    level_cm=Decimal("18.0"),
                    recorded_at=now - timedelta(hours=1),
                    recorded_by=agent,
                )
            for visit_day in rng.sample(range(1, days), 2):
                FieldVisit.objects.create(
                    field=field,
                    visitor=agent,
                    visited_at=now - timedelta(days=visit_day, hours=3),
                    crop_stage=rng.choice([FieldVisit.CropStage.TILLERING, FieldVisit.CropStage.PANICLE]),
                    notes=rng.choice(
                        [
                            "Pipe clear, farmer following AWD schedule.",
                            "Some weed pressure on the bund; advised manual weeding.",
                            "Farmer reports pump diesel cost down vs last season.",
                            "Minor leaf discolouration, suggested urea top-dress after re-flooding.",
                        ]
                    ),
                    lat=field.centroid_lat + rng.uniform(-0.0003, 0.0003),
                    lng=field.centroid_lng + rng.uniform(-0.0003, 0.0003),
                )

        check = run_awd_check(as_of=now)
        self.stdout.write(
            self.style.SUCCESS(
                f"seeded {len(FARMERS)} farmers, {len(fields)} fields, {readings} readings; "
                f"AWD check opened {check.opened} alerts"
            )
        )
        self.stdout.write("demo login: username=agent password=agent1234 (use POST /api/v1/auth/token/)")
