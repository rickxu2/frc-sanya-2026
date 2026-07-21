#!/usr/bin/env python3
"""
Auto-refresh for the Sanya FRC analytics site.

Run every few minutes by the Windows Task Scheduler. Each run:
  1. fetches the latest FRC Events data + recomputes analysis.json (build.py),
  2. checks whether the raw API data (matches/scores/rankings/...) actually
     changed,
  3. if it did, commits and pushes so GitHub Pages redeploys; otherwise reverts
     the (timestamp-only) change and does nothing.

So the live site updates within a few minutes of each match result, and there
are no empty "nothing changed" commits. All output is appended to
logs/refresh.log. Credentials come from the local .env (never committed);
git push uses the gh credential helper.
"""
import os
import sys
import subprocess
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGDIR = os.path.join(ROOT, "logs")
LOG = os.path.join(LOGDIR, "refresh.log")
PY = sys.executable  # pythonw.exe when launched by the scheduler
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # suppress child console popups


def log(msg):
    os.makedirs(LOGDIR, exist_ok=True)
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line)
    except Exception:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          creationflags=NO_WINDOW)


def git(*args):
    return run(["git", *args])


def last_line(s):
    lines = [x for x in (s or "").strip().splitlines() if x.strip()]
    return lines[-1] if lines else ""


def main():
    # 1) fetch + recompute
    r = run([PY, os.path.join(HERE, "build.py")])
    if r.returncode != 0:
        log("build FAILED (rc=%d): %s" % (r.returncode, last_line(r.stderr) or last_line(r.stdout)))
        return

    # 2) did the raw API data change? (status catches modified + new files)
    st = git("status", "--porcelain", "--", "data/raw")
    if not st.stdout.strip():
        # only the generatedAt timestamp changed in analysis.json — revert it
        git("checkout", "--", "docs/data/analysis.json")
        log("no new data")
        return

    # 3) commit + push
    git("add", "-A")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    c = git("commit", "-m", "data: auto-refresh %s" % stamp)
    if c.returncode != 0:
        log("commit skipped: %s" % (last_line(c.stdout) or last_line(c.stderr)))
        return
    p = git("push", "origin", "main")
    if p.returncode != 0:
        log("PUSH FAILED: %s" % (last_line(p.stderr) or last_line(p.stdout)))
        return
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    changed = git("show", "--stat", "--oneline", "HEAD").stdout
    n = changed.count("data/raw/")
    log("PUSHED %s (%d raw file(s) changed) -> site will redeploy" % (head, n))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never let the scheduler see an unhandled crash
        log("ERROR: %r" % e)
