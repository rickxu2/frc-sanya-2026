#!/usr/bin/env python3
"""
One-shot build: fetch raw data from the FRC Events API, then compute
docs/data/analysis.json for the static site.

Credentials come from environment variables, or from a local `.env` file
(gitignored) in the project root:

    FRC_API_USERNAME=your_username
    FRC_API_TOKEN=your_token
    # optional overrides:
    # FRC_SEASON=2026
    # FRC_EVENT=OTSAN

Usage:
    python scripts/build.py            # fetch + compute
    python scripts/build.py --compute  # recompute only (skip fetch)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def load_dotenv():
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)


def main():
    load_dotenv()
    compute_only = "--compute" in sys.argv
    if not compute_only:
        import fetch_data
        fetch_data.main()
    import compute_analysis
    compute_analysis.main()


if __name__ == "__main__":
    main()
