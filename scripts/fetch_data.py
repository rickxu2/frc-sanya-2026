#!/usr/bin/env python3
"""
Fetch all available data for an FRC event from the official FRC Events API
(the same source behind frc-events.firstinspires.org) and dump the raw JSON
responses to data/raw/.

Credentials are read from environment variables and are NEVER written to disk:
    FRC_API_USERNAME  - your FRC Events API username
    FRC_API_TOKEN     - your FRC Events API authorization token

Usage:
    FRC_API_USERNAME=you FRC_API_TOKEN=xxxx python scripts/fetch_data.py
    (defaults: season=2026, event=OTSAN)
"""
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = "https://frc-api.firstinspires.org/v3.0"
SEASON = os.environ.get("FRC_SEASON", "2026")
EVENT = os.environ.get("FRC_EVENT", "OTSAN")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")


def auth_header():
    user = os.environ.get("FRC_API_USERNAME", "")
    token = os.environ.get("FRC_API_TOKEN", "")
    if not user or not token:
        sys.exit(
            "ERROR: set FRC_API_USERNAME and FRC_API_TOKEN environment variables.\n"
            "Register (free, instant) at https://frc-events.firstinspires.org/services/API"
        )
    raw = f"{user}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def get(path, params=None):
    """GET a JSON endpoint. Returns (status, data-or-None, error-text)."""
    url = f"{BASE}/{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", auth_header())
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "sanya-frc-analytics/1.0")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body), None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        return e.code, None, detail
    except Exception as e:  # noqa
        return 0, None, str(e)


def save(name, data):
    os.makedirs(RAW_DIR, exist_ok=True)
    p = os.path.join(RAW_DIR, name + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def fetch(label, name, path, params=None, required=False):
    status, data, err = get(path, params)
    if status == 200 and data is not None:
        save(name, data)
        # crude count for the summary line
        count = ""
        if isinstance(data, dict):
            for k in ("matches", "MatchScores", "teams", "Rankings",
                      "Schedule", "Alliances", "Awards", "events"):
                if k in data and isinstance(data[k], list):
                    count = f"({len(data[k])} {k})"
                    break
        print(f"  OK   {label:<22} {count}")
        return data
    else:
        flag = "FAIL" if required else "skip"
        print(f"  {flag} {label:<22} HTTP {status} {err[:120] if err else ''}")
        if required:
            sys.exit(f"Aborting: required endpoint '{label}' failed.")
        return None


def fetch_paginated_teams():
    """Teams endpoint is paginated."""
    all_teams = []
    page = 1
    meta = None
    while True:
        status, data, err = get(f"{SEASON}/teams",
                                {"eventCode": EVENT, "page": page})
        if status != 200 or not data:
            if page == 1:
                print(f"  skip teams                  HTTP {status} {err[:80] if err else ''}")
            break
        meta = {k: v for k, v in data.items() if k != "teams"}
        chunk = data.get("teams", [])
        all_teams.extend(chunk)
        total_pages = data.get("pageTotal", 1)
        if page >= total_pages or not chunk:
            break
        page += 1
        time.sleep(0.2)
    if all_teams:
        save("teams", {"teams": all_teams, **(meta or {})})
        print(f"  OK   teams                  ({len(all_teams)} teams)")
    return all_teams


def main():
    print(f"Fetching FRC Events data: season={SEASON} event={EVENT}")
    print(f"Output: {RAW_DIR}")
    print("-" * 60)

    fetch("event",          "event",          f"{SEASON}/events", {"eventCode": EVENT}, required=True)
    fetch_paginated_teams()

    # Match results (teams + summary scores) and detailed score breakdowns
    fetch("matches/qual",   "matches_qual",   f"{SEASON}/matches/{EVENT}", {"tournamentLevel": "qual"})
    fetch("matches/playoff","matches_playoff",f"{SEASON}/matches/{EVENT}", {"tournamentLevel": "playoff"})
    fetch("scores/qual",    "scores_qual",    f"{SEASON}/scores/{EVENT}/qual")
    fetch("scores/playoff", "scores_playoff", f"{SEASON}/scores/{EVENT}/playoff")

    # Schedule (planned team assignments; useful before results are posted)
    fetch("schedule/qual",  "schedule_qual",  f"{SEASON}/schedule/{EVENT}", {"tournamentLevel": "qual"})
    fetch("schedule/playoff","schedule_playoff",f"{SEASON}/schedule/{EVENT}", {"tournamentLevel": "playoff"})

    # Standings / bracket / awards (some may be absent at an off-season event)
    fetch("rankings",       "rankings",       f"{SEASON}/rankings/{EVENT}")
    fetch("alliances",      "alliances",      f"{SEASON}/alliances/{EVENT}")
    fetch("awards",         "awards",         f"{SEASON}/awards/event/{EVENT}")

    print("-" * 60)
    print("Done.")


if __name__ == "__main__":
    main()
