"""
Refreshes the Partner Occasions & Gifting Board.

The board's data (the `RAW` array and `INCOMPLETE` list) is embedded
directly inside index.html, between the markers:

    // ---BEGIN-RAW-DATA---
    ...
    // ---END-RAW-DATA---

This script:
  1. Downloads the Google Form responses sheet as CSV.
  2. Maps its columns onto the fields the board expects
     (ts, name, status, dob, anniv, color, food, company, position, tenure).
  3. Splits rows into "real" submissions vs. incomplete stubs (rows
     missing a timestamp, or missing both company and position).
  4. Rewrites the block between the markers in index.html with fresh data.

SETUP (one-time)
-----------------
1. In the Google Sheet the Form writes to: File > Share > Publish to web
   > choose the response sheet/tab > CSV. Copy that URL.
2. In the GitHub repo: Settings > Secrets and variables > Actions >
   New repository secret, name it SHEET_CSV_URL, paste the link.
3. If your Form's actual column headers differ a lot from the guesses
   in HEADER_MAP below, adjust HEADER_MAP to match.
"""

import csv
import io
import json
import os
import re
import sys

import requests

SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL")
INDEX_HTML_PATH = "index.html"

BEGIN_MARKER = "// ---BEGIN-RAW-DATA---"
END_MARKER = "// ---END-RAW-DATA---"

# Maps our internal field name -> list of substrings to look for in the
# CSV header row (case-insensitive). First match wins.
HEADER_MAP = {
    "ts": ["timestamp"],
    "name": ["name"],
    "status": ["status", "civil status", "married"],
    "dob": ["birth", "dob", "date of birth"],
    "anniv": ["anniversary"],
    "color": ["color", "colour"],
    "food": ["food"],
    "company": ["company", "school", "institution"],
    "position": ["position", "title", "designation"],
    "tenure": ["tenure", "years with", "length of service"],
}


def fetch_rows(csv_url: str):
    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = rows[0]
    return headers, rows[1:]


def map_headers(headers):
    """Return {field_name: column_index} based on HEADER_MAP."""
    mapping = {}
    lower_headers = [h.strip().lower() for h in headers]
    for field, keywords in HEADER_MAP.items():
        for i, h in enumerate(lower_headers):
            if any(kw in h for kw in keywords):
                mapping[field] = i
                break
    return mapping


def clean(value: str) -> str:
    return (value or "").strip()


def js_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_entries(headers, data_rows):
    mapping = map_headers(headers)
    missing = [f for f in ("ts", "name") if f not in mapping]
    if missing:
        print(f"ERROR: couldn't find columns for: {missing}. "
              f"Headers seen: {headers}", file=sys.stderr)
        sys.exit(1)

    complete, incomplete_names = [], []

    for row in data_rows:
        def get(field):
            idx = mapping.get(field)
            if idx is None or idx >= len(row):
                return ""
            return clean(row[idx])

        entry = {
            "ts": get("ts"),
            "name": get("name"),
            "status": get("status"),
            "dob": get("dob"),
            "anniv": get("anniv"),
            "color": get("color"),
            "food": get("food"),
            "company": get("company"),
            "position": get("position"),
            "tenure": get("tenure"),
        }

        if not entry["name"]:
            continue  # blank row

        # Same heuristic the board already used: no timestamp, or missing
        # both company and position -> treat as an incomplete stub.
        is_incomplete = (not entry["ts"]) or (not entry["company"] and not entry["position"])

        if is_incomplete:
            incomplete_names.append(entry["name"])
        else:
            complete.append(entry)

    return complete, sorted(set(incomplete_names))


def render_js_block(entries, incomplete_names):
    lines = []
    lines.append(BEGIN_MARKER)
    lines.append("// ---------- Raw data pulled from the Google Form response sheet ----------")
    lines.append("const RAW = [")
    for e in entries:
        fields = ", ".join(f'{k}:"{js_escape(v)}"' for k, v in e.items())
        lines.append(f" {{{fields}}},")
    lines.append("];")
    lines.append("")
    lines.append("// Rows with no timestamp / mostly blank contact+company fields (likely stubs, not real submissions)")
    names_js = ",".join(f'"{js_escape(n)}"' for n in incomplete_names)
    lines.append(f"const INCOMPLETE = [{names_js}];")
    lines.append(END_MARKER)
    return "\n".join(lines)


def main():
    if not SHEET_CSV_URL:
        print("ERROR: SHEET_CSV_URL is not set. Add it as a repo secret.", file=sys.stderr)
        sys.exit(1)

    headers, data_rows = fetch_rows(SHEET_CSV_URL)
    entries, incomplete_names = build_entries(headers, data_rows)
    new_block = render_js_block(entries, incomplete_names)

    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    pattern = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )
    if not pattern.search(html):
        print(f"ERROR: markers {BEGIN_MARKER!r} / {END_MARKER!r} not found in {INDEX_HTML_PATH}.",
              file=sys.stderr)
        sys.exit(1)

    updated_html = pattern.sub(lambda _: new_block, html, count=1)

    with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(updated_html)

    print(f"Wrote {len(entries)} entries and {len(incomplete_names)} incomplete stubs to {INDEX_HTML_PATH}")


if __name__ == "__main__":
    main()
