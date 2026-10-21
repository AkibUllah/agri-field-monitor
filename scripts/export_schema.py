"""Export the GraphQL SDL without a database file or a .env file.

    strawberry export-schema scripts.export_schema:schema --app-dir . > schema.graphql
    python scripts/export_schema.py [output path]        # same SDL, no strawberry[cli] needed

strawberry-django types touch the model registry on import, so Django is set up here
before ``api.schema`` is imported. The GitHub Pages workflow publishes the result.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import django  # noqa: E402

django.setup()

from api.schema import schema  # noqa: E402


def main(argv: list[str]) -> int:
    sdl = schema.as_str().rstrip("\n") + "\n"
    if len(argv) > 1:
        out = Path(argv[1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(sdl, encoding="utf-8")
        print(f"wrote {out} ({sdl.count(chr(10))} lines)")
    else:
        sys.stdout.write(sdl)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
