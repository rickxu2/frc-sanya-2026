# 三亚 FRC 2026 (REBUILT) 数据分析 · Sanya OTSAN Analytics

An interactive analytics dashboard for the **2026 FRC _REBUILT_ Sanya event
(`OTSAN`)** — *World Robot Contest South China Championships 2026, Sanya*.

It fetches match data from the official **[FRC Events API](https://frc-events.firstinspires.org/services/API)**,
independently computes **OPR** and a family of component / per-shift OPR variants
(plus OPR-over-time trends), and renders a static site with a clickable **“?”**
explanation on every metric.

**Live site:** <https://rickxu2.github.io/frc-sanya-2026/>

## What it computes

- **Power ratings** — OPR, DPR, CCWM (least-squares from match scores).
- **Phase OPR** — Auto / Teleop / Endgame OPR.
- **REBUILT-specific** — Fuel OPR, Fuel-count OPR, Tower OPR, and per-**Shift**
  fuel OPR when the data source exposes per-shift detail.
- **Trends** — OPR (and components) recomputed after each qualification match.
- **Record** — W-L-T, win rate, average RP, and Energized / Supercharged /
  Traversal RP rates.

Every metric’s definition and method is documented in-app (the **指标说明** and
**方法** tabs) and via the inline **?** buttons.

## How it works

```
scripts/fetch_data.py   → data/raw/*.json     (raw FRC Events API responses)
scripts/compute_analysis.py → docs/data/analysis.json  (OPR etc.)
docs/                    → static site (GitHub Pages)
```

The site is 100% static (no backend); Chart.js is vendored locally, so there are
**no external/CDN dependencies**. Your API key is only used locally at build time
and is **never** committed — only the processed `analysis.json` ships.

## Rebuild the data

1. Get a free FRC Events API key at
   <https://frc-events.firstinspires.org/services/API> (instant).
2. Create a `.env` file in the project root (it is gitignored):

   ```
   FRC_API_USERNAME=your_username
   FRC_API_TOKEN=your_token
   ```

3. Run (Python 3, no dependencies needed):

   ```
   python scripts/build.py
   ```

   This refetches and recomputes `docs/data/analysis.json`. Commit and push to
   update the live site.

To preview locally:

```
python -m http.server 8765 --directory docs
# open http://127.0.0.1:8765
```

## Automatic refresh

[scripts/refresh.py](scripts/refresh.py) refetches the data and **commits + pushes
only when the raw match/score data actually changed** (so no empty commits, and the
site updates within a few minutes of each match). On this machine it runs every
5 minutes via a Windows Scheduled Task named **`SanyaFRCRefresh`**; output is logged
to `logs/refresh.log`.

```powershell
# see / run / disable the task
Get-ScheduledTask SanyaFRCRefresh
Start-ScheduledTask SanyaFRCRefresh      # run once now
Disable-ScheduledTask SanyaFRCRefresh    # stop auto-refresh (e.g. after the event)
```

## Notes & limitations

- OPR assumes alliance score = sum of independent team contributions; it ignores
  synergy and defense interactions.
- Early in an event (few matches) OPR is noisy — interpret with care.
- This is an independent tool and is **not affiliated with _FIRST_®**.
