"""Render the static GraphQL reference page for GitHub Pages.

    python scripts/build_schema_page.py schema.graphql _site

Reads the SDL, injects it (HTML-escaped) into site/template.html and writes
``<out dir>/index.html`` plus a copy of the SDL as ``<out dir>/schema.graphql``.
"""

from __future__ import annotations

import html
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "site" / "template.html"
PLACEHOLDER = "<!-- SDL -->"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    sdl_path, out_dir = Path(argv[1]), Path(argv[2])
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE} has no {PLACEHOLDER} marker")
    sdl = sdl_path.read_text(encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(template.replace(PLACEHOLDER, html.escape(sdl)), "utf-8")
    shutil.copyfile(sdl_path, out_dir / "schema.graphql")
    print(f"wrote {out_dir / 'index.html'} and schema.graphql ({sdl.count(chr(10))} SDL lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
