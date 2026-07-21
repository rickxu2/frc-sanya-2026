#!/usr/bin/env python3
"""
Turn the raw FRC Events API JSON (in data/raw/) into docs/data/analysis.json,
computing OPR and a rich family of component / per-shift OPR variants,
OPR-over-time trends, per-team records, RP rates and climb rates.

REBUILT (2026) score breakdown — key fields (confirmed from the API):
  totalPoints, totalAutoPoints, totalTeleopPoints, totalTowerPoints,
  autoTowerPoints, endGameTowerPoints,
  autoTowerRobot{1..3}, endGameTowerRobot{1..3}   (per-robot climb level string),
  hubScore = { autoCount/Points, transitionCount/Points,
               shift1..4 Count/Points, endgameCount/Points,
               teleopCount/Points, totalCount/Points, uncounted },
  energizedAchieved, superchargedAchieved, traversalAchieved, rp, foulPoints

Run after scripts/fetch_data.py:   python scripts/compute_analysis.py
No third-party dependencies (uses scripts/linalg.py for least squares).
"""
import json
import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "docs", "data", "analysis.json")
sys.path.insert(0, HERE)
from linalg import opr as solve_opr  # noqa: E402

RIDGE = 0.5  # regularization — keeps OPR stable at low match counts


def load(name):
    p = os.path.join(RAW, name + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------- REBUILT breakdown extract
def extract(bd):
    """Pull every scoring component out of one alliance's breakdown dict."""
    if not bd:
        return {}
    c = {
        "total": num(bd.get("totalPoints")),
        "auto": num(bd.get("totalAutoPoints")),
        "teleop": num(bd.get("totalTeleopPoints")),
        "tower": num(bd.get("totalTowerPoints")),
        "autoTower": num(bd.get("autoTowerPoints")),
        "endgameTower": num(bd.get("endGameTowerPoints")),
        "foul": num(bd.get("foulPoints")),
    }
    hub = bd.get("hubScore")
    if isinstance(hub, dict):
        c["fuel"] = num(hub.get("totalPoints"))
        # throughput = fuel delivered to the hub, incl. pieces that didn't score
        # because the hub was inactive (1 scored fuel = 1 point, so scored count
        # equals fuel points; adding `uncounted` makes this a distinct metric).
        tc = num(hub.get("totalCount"))
        c["fuelCount"] = (tc + (num(hub.get("uncounted")) or 0)) if tc is not None else None
        c["autoFuel"] = num(hub.get("autoPoints"))
        c["teleopFuel"] = num(hub.get("teleopPoints"))
        c["transition"] = num(hub.get("transitionPoints"))
        c["endgameFuel"] = num(hub.get("endgamePoints"))
        for i in (1, 2, 3, 4):
            c["shift%d" % i] = num(hub.get("shift%dPoints" % i))
            c["shift%dCount" % i] = num(hub.get("shift%dCount" % i))
    elif hub is not None:
        c["fuel"] = num(hub)
    c["_rp"] = {
        "energized": bool(bd.get("energizedAchieved")),
        "supercharged": bool(bd.get("superchargedAchieved")),
        "traversal": bool(bd.get("traversalAchieved")),
    }
    c["_rpEarned"] = num(bd.get("rp"))
    c["_climb"] = {i: bd.get("endGameTowerRobot%d" % i) for i in (1, 2, 3)}
    c["_autoClimb"] = {i: bd.get("autoTowerRobot%d" % i) for i in (1, 2, 3)}
    return c


def climbed(level):
    """True if a per-robot tower level string represents an actual climb."""
    if not level:
        return False
    return str(level).strip().lower() not in ("none", "no", "unknown", "notattempted", "")


# --------------------------------------------------------------- match parsing
def parse_matches(level):
    """Join matches_<level>.json (teams + finals) with scores_<level>.json
    (breakdown). Returns list of match dicts with per-station team mapping."""
    mj = load("matches_" + level) or {}
    sj = load("scores_" + level) or {}
    matches_list = mj.get("Matches") or mj.get("matches") or []
    scores_list = sj.get("MatchScores") or sj.get("matchScores") or []

    score_idx = {}
    for s in scores_list:
        score_idx[s.get("matchNumber")] = {a.get("alliance"): a for a in s.get("alliances", [])}

    out = []
    for m in matches_list:
        mn = m.get("matchNumber")
        stations = {"Red": {}, "Blue": {}}
        red, blue = [], []
        for t in m.get("teams", []):
            st = t.get("station") or ""
            tn = t.get("teamNumber")
            if tn is None:
                continue
            side = "Red" if st.startswith("Red") else ("Blue" if st.startswith("Blue") else None)
            if not side:
                continue
            idx = None
            if st and st[-1].isdigit():
                idx = int(st[-1])
            if idx:
                stations[side][idx] = tn
            (red if side == "Red" else blue).append(tn)
        alls = score_idx.get(mn, {})
        comps = {"Red": extract(alls.get("Red", {})), "Blue": extract(alls.get("Blue", {}))}
        red_final = num(m.get("scoreRedFinal"))
        blue_final = num(m.get("scoreBlueFinal"))
        if comps["Red"].get("total") is None and red_final is not None:
            comps["Red"]["total"] = red_final
        if comps["Blue"].get("total") is None and blue_final is not None:
            comps["Blue"]["total"] = blue_final
        out.append({
            "level": level, "num": mn, "desc": m.get("description"),
            "red": red, "blue": blue, "stations": stations,
            "redScore": red_final, "blueScore": blue_final, "comps": comps,
            "played": bool(m.get("postResultTime")) or (red_final is not None),
        })
    return out


# --------------------------------------------------------------- OPR machinery
def appearances(matches, comp_key, opponents=False, margin=False):
    rows = []
    for mm in matches:
        if not mm["played"]:
            continue
        for color, opp in (("Red", "Blue"), ("Blue", "Red")):
            teams = mm[color.lower()]
            if not teams:
                continue
            if margin:
                a, b = mm["comps"][color].get("total"), mm["comps"][opp].get("total")
                if a is None or b is None:
                    continue
                val = a - b
            elif opponents:
                val = mm["comps"][opp].get("total")
            else:
                val = mm["comps"][color].get(comp_key)
            if val is None:
                continue
            rows.append((tuple(teams), val))
    return rows


def has_data(rows):
    return len(rows) >= 3


# metricKey -> component key solved by least squares over alliance value
COMP_METRIC = {
    "opr": "total", "autoOpr": "auto", "teleopOpr": "teleop", "towerOpr": "tower",
    "autoTowerOpr": "autoTower", "endgameTowerOpr": "endgameTower",
    "fuelOpr": "fuel", "fuelCountOpr": "fuelCount",
    "autoFuelOpr": "autoFuel", "teleopFuelOpr": "teleopFuel",
    "transitionOpr": "transition", "endgameFuelOpr": "endgameFuel",
    "shift1Opr": "shift1", "shift2Opr": "shift2", "shift3Opr": "shift3", "shift4Opr": "shift4",
}
TREND_METRICS = ["opr", "autoOpr", "teleopOpr", "fuelOpr", "towerOpr"]


# ---------------------------------------------------------------- metric defs
D = lambda label, full, help, unit="分", dec=1, higher=True: {  # noqa: E731
    "label": label, "full": full, "unit": unit, "decimals": dec, "higherBetter": higher, "help": help}

METRIC_DEFS = {
    "opr": D("OPR", "Offensive Power Rating 进攻贡献值",
             "OPR 用最小二乘法从所有比赛的联盟总得分中，估计每支队伍对联盟得分的平均贡献。数值越高表示该队进攻端贡献越大。它自动剔除了队友和对手的影响，是衡量单队实力最常用的指标。"),
    "dpr": D("DPR", "Defensive Power Rating 防守/失分贡献值",
             "DPR 用同样的最小二乘法，但拟合的是对方联盟的得分——即该队所在联盟“让对手拿到”的分数中可归因于该队的部分。数值越低越好，通常反映防守或压制能力。", higher=False),
    "ccwm": D("CCWM", "Calculated Contribution to Winning Margin 净胜分贡献",
              "CCWM = OPR − DPR，等价于对“净胜分（本方得分 − 对方得分）”做最小二乘。它同时考虑进攻和防守，衡量该队对赢下比赛的综合贡献。"),
    "autoOpr": D("Auto OPR", "自动阶段 OPR",
                 "只用每场比赛自动阶段（前 20 秒）的联盟得分做 OPR 拟合。REBUILT 自动阶段得分 = 自动投料入 Hub + 自动爬塔（L1 挂机 15 分）。"),
    "teleopOpr": D("Teleop OPR", "手动阶段 OPR",
                   "只用手动阶段（Teleop，含 4 个班次）联盟得分做 OPR 拟合，衡量该队手动阶段的总贡献，主要来自持续向 Hub 投送燃料。"),
    "towerOpr": D("Tower OPR", "爬塔总 OPR",
                  "只用塔（Tower）总得分做 OPR 拟合（含自动与终局爬塔）。爬塔按高度计分：L1/L2/L3 = 10/20/30 分，自动挂 L1 为 15 分。"),
    "autoTowerOpr": D("AutoTower OPR", "自动爬塔 OPR",
                      "只用自动阶段爬塔得分做 OPR 拟合，衡量该队在自动阶段挂塔（如 L1 挂机 15 分）的贡献。"),
    "endgameTowerOpr": D("Endgame Tower OPR", "终局爬塔 OPR",
                         "只用终局阶段爬塔得分做 OPR 拟合，衡量该队在比赛最后的爬塔贡献（L1/L2/L3 = 10/20/30 分）。"),
    "fuelOpr": D("Fuel OPR", "燃料/Hub 得分 OPR",
                 "只用投入 Hub 的燃料总得分（hubScore）做 OPR 拟合，剥离爬塔与犯规，衡量该队纯投料的得分贡献。"),
    "fuelCountOpr": D("Fuel# OPR", "燃料吞吐量 OPR",
                      "以“投入 Hub 的燃料总数”（含因 Hub 未激活而未计分的 uncounted 部分）做 OPR 拟合，衡量该队的投料机构吞吐量，不受班次激活时序影响——与只算计分燃料的 Fuel OPR 互补。", unit="个"),
    "autoFuelOpr": D("Auto Fuel OPR", "自动投料 OPR",
                     "只用自动阶段投入 Hub 的燃料得分做 OPR 拟合，衡量该队自动阶段的投料能力。"),
    "teleopFuelOpr": D("Teleop Fuel OPR", "手动投料 OPR",
                       "只用手动阶段（含转场与 4 个班次、终局窗口）投入 Hub 的燃料得分做 OPR 拟合。"),
    "transitionOpr": D("Transition OPR", "转场班次(10s) OPR",
                       "手动阶段开始有一个 10 秒的转场班次（Transition），此指标只用转场班次内的燃料得分做 OPR 拟合。"),
    "shift1Opr": D("Shift 1 OPR", "第 1 班次(25s) OPR",
                   "REBUILT 手动阶段分为 4 个 25 秒班次（Shift），两队 Hub 轮流激活——得分次序由自动阶段表现决定。此指标只用第 1 班次内的燃料得分做 OPR 拟合，衡量该队在该班次窗口的投料效率。"),
    "shift2Opr": D("Shift 2 OPR", "第 2 班次(25s) OPR",
                   "只用第 2 个 25 秒班次内投入 Hub 的燃料得分做 OPR 拟合。班次得分反映该队在对应激活窗口的投料效率。"),
    "shift3Opr": D("Shift 3 OPR", "第 3 班次(25s) OPR",
                   "只用第 3 个 25 秒班次内投入 Hub 的燃料得分做 OPR 拟合。"),
    "shift4Opr": D("Shift 4 OPR", "第 4 班次(25s) OPR",
                   "只用第 4 个 25 秒班次内投入 Hub 的燃料得分做 OPR 拟合。"),
    "endgameFuelOpr": D("Endgame Fuel OPR", "终局投料 OPR",
                        "只用终局窗口内投入 Hub 的燃料得分做 OPR 拟合（与爬塔分开计）。"),
    "climbRate": D("爬塔率", "Endgame Climb Rate",
                   "该队在其已打比赛中，终局成功爬塔（任意高度）的场次比例，来自逐机器人的爬塔高度记录。", unit="%", dec=0),
    "rank": D("排名", "Ranking 官方排名",
              "赛事官方排位赛排名，依据排位分（Ranking Points）等排序规则得出。", unit="", dec=0, higher=False),
    "matchesPlayed": D("出场", "Matches Played",
                       "该队已完成的排位赛场次。场次很少时，OPR 等指标噪声较大，请结合此列谨慎解读。", unit="场", dec=0),
    "winRate": D("胜率", "Win Rate",
                 "该队所在联盟获胜的场次占其已打场次的比例。", unit="%", dec=0),
    "avgRp": D("均 RP", "Average Ranking Points 场均排位分",
               "场均获得的排位分（RP，来自每场比赛的 rp 字段）。REBUILT 中赢球得基础 RP，另有 Energized(累计投料100)、Supercharged(累计投料360)、Traversal(塔分50) 等成就 RP。", unit="", dec=2),
    "avgScore": D("场均得分", "Average Alliance Score",
                  "该队所在联盟每场的平均总得分（含队友与对手影响，仅供参考，不如 OPR 精确）。"),
    "energizedRpRate": D("Energized%", "Energized RP 达成率",
                         "该队所在联盟达成 Energized RP（累计燃料得分达到 100）的场次比例。", unit="%", dec=0),
    "superchargedRpRate": D("Supercharged%", "Supercharged RP 达成率",
                            "该队所在联盟达成 Supercharged RP（累计燃料得分达到 360）的场次比例。", unit="%", dec=0),
    "traversalRpRate": D("Traversal%", "Traversal RP 达成率",
                         "该队所在联盟达成 Traversal RP（塔得分累计达到 50）的场次比例。", unit="%", dec=0),
}

METRIC_GROUPS = [
    {"key": "power", "label": "综合能力 · Power Ratings", "metrics": ["opr", "dpr", "ccwm"]},
    {"key": "phase", "label": "阶段得分 · Phase OPR", "metrics": ["autoOpr", "teleopOpr", "towerOpr"]},
    {"key": "fuel", "label": "投料 · Fuel OPR", "metrics": ["fuelOpr", "fuelCountOpr", "autoFuelOpr", "teleopFuelOpr"]},
    {"key": "shift", "label": "分班次 · Per-Shift OPR", "metrics": ["transitionOpr", "shift1Opr", "shift2Opr", "shift3Opr", "shift4Opr", "endgameFuelOpr"]},
    {"key": "climb", "label": "爬塔 · Tower/Climb", "metrics": ["autoTowerOpr", "endgameTowerOpr", "climbRate"]},
    {"key": "record", "label": "战绩 · Record", "metrics": ["rank", "matchesPlayed", "winRate", "avgRp", "avgScore", "energizedRpRate", "superchargedRpRate", "traversalRpRate"]},
]


# ------------------------------------------------------------------- assemble
def main():
    ev = ((load("event") or {}).get("Events") or [{}])[0]
    teams_raw = (load("teams") or {}).get("teams", [])
    if not teams_raw:
        sys.exit("No teams found in data/raw/teams.json — run fetch_data.py first.")

    team_index, team_meta = {}, {}
    for i, t in enumerate(sorted(teams_raw, key=lambda x: x.get("teamNumber", 0))):
        tn = t.get("teamNumber")
        team_index[tn] = i
        team_meta[tn] = {
            "team": tn, "name": t.get("nameShort") or ("Team %s" % tn),
            "school": t.get("nameFull") or "", "city": t.get("city") or "",
            "country": t.get("country") or "",
        }

    qual = parse_matches("qual")
    playoff = parse_matches("playoff")
    all_matches = qual + playoff
    played_qual = [m for m in qual if m["played"]]

    inspect_report()

    # ---- solve OPR family over qual matches -------------------------------
    solved = {}
    for mk, ck in COMP_METRIC.items():
        rows = appearances(played_qual, ck)
        if has_data(rows):
            solved[mk] = solve_opr(rows, team_index, ridge=RIDGE)
    for mk, kw in (("dpr", dict(opponents=True)), ("ccwm", dict(margin=True))):
        rows = appearances(played_qual, "total", **kw)
        if has_data(rows):
            solved[mk] = solve_opr(rows, team_index, ridge=RIDGE)

    # ---- per-team record / RP / climb from qual matches -------------------
    rec = {tn: {"w": 0, "l": 0, "t": 0, "scoreSum": 0.0, "n": 0,
                "rpSum": 0.0, "rpN": 0,
                "rp": {"energized": 0, "supercharged": 0, "traversal": 0}, "rpFlagN": 0,
                "climbN": 0, "climbYes": 0} for tn in team_index}
    for m in played_qual:
        rs, bs = m["redScore"], m["blueScore"]
        for color, teams, own, opp in (("Red", m["red"], rs, bs), ("Blue", m["blue"], bs, rs)):
            comp = m["comps"][color]
            rpflags = comp.get("_rp", {})
            rp_earned = comp.get("_rpEarned")
            for tn in teams:
                r = rec.get(tn)
                if not r:
                    continue
                r["n"] += 1
                if own is not None and opp is not None:
                    r["scoreSum"] += own
                    if own > opp:
                        r["w"] += 1
                    elif own < opp:
                        r["l"] += 1
                    else:
                        r["t"] += 1
                if rp_earned is not None:
                    r["rpSum"] += rp_earned
                    r["rpN"] += 1
                if any(rpflags.values()) or rp_earned is not None:
                    r["rpFlagN"] += 1
                    for nm in ("energized", "supercharged", "traversal"):
                        if rpflags.get(nm):
                            r["rp"][nm] += 1
            # per-robot climb (station index -> team)
            for idx, tn in m["stations"][color].items():
                r = rec.get(tn)
                if not r:
                    continue
                lvl = comp.get("_climb", {}).get(idx)
                if lvl is not None:
                    r["climbN"] += 1
                    if climbed(lvl):
                        r["climbYes"] += 1

    # rankings passthrough (rank; avgRp fallback)
    rankings = (load("rankings") or {}).get("Rankings") or (load("rankings") or {}).get("rankings") or []
    rank_by_team = {r.get("teamNumber"): r.get("rank") for r in rankings}

    # ---- OPR-over-time trends --------------------------------------------
    trend_keys = [mk for mk in TREND_METRICS if mk in solved]
    trends = compute_trends(qual, team_index, trend_keys)

    # ---- build teams ------------------------------------------------------
    teams_out = []
    for tn, meta in team_meta.items():
        metrics = {}
        for mk, table in solved.items():
            if tn in table:
                metrics[mk] = round(table[tn], 2)
        r = rec[tn]
        mp = r["w"] + r["l"] + r["t"]
        if mp:
            metrics["matchesPlayed"] = mp
        if r["n"]:
            metrics["winRate"] = round(100.0 * r["w"] / r["n"])
            if r["scoreSum"]:
                metrics["avgScore"] = round(r["scoreSum"] / r["n"], 1)
        if r["rpN"]:
            metrics["avgRp"] = round(r["rpSum"] / r["rpN"], 2)
        if r["rpFlagN"]:
            metrics["energizedRpRate"] = round(100.0 * r["rp"]["energized"] / r["rpFlagN"])
            metrics["superchargedRpRate"] = round(100.0 * r["rp"]["supercharged"] / r["rpFlagN"])
            metrics["traversalRpRate"] = round(100.0 * r["rp"]["traversal"] / r["rpFlagN"])
        if r["climbN"]:
            metrics["climbRate"] = round(100.0 * r["climbYes"] / r["climbN"])
        team_trends = {mk: trends[mk].get(tn, []) for mk in trend_keys if trends[mk].get(tn)}
        teams_out.append({
            "team": tn, "name": meta["name"], "school": meta["school"],
            "country": meta["country"], "rank": rank_by_team.get(tn),
            "record": {"w": r["w"], "l": r["l"], "t": r["t"]},
            "metrics": metrics, "trends": team_trends,
            "matches": team_match_rows(tn, all_matches),
        })
    teams_out.sort(key=lambda t: (t["rank"] is None, t["rank"] if t["rank"] is not None else 1e9,
                                  -(t["metrics"].get("opr") or -1e9)))

    # ---- available metric defs / groups ----------------------------------
    present = set()
    for t in teams_out:
        present |= set(t["metrics"].keys())
    present.add("rank")
    defs_out = {k: v for k, v in METRIC_DEFS.items() if k in present}
    groups_out = [{"key": g["key"], "label": g["label"],
                   "metrics": [m for m in g["metrics"] if m in present]}
                  for g in METRIC_GROUPS]
    groups_out = [g for g in groups_out if g["metrics"]]

    meta = {
        "event": ev.get("code") or os.environ.get("FRC_EVENT", "OTSAN"),
        "eventName": ev.get("name") or "Sanya 三亚 (OTSAN)",
        "eventShort": "Sanya 三亚",
        "eventDates": fmt_dates(ev),
        "eventUrl": "https://frc-events.firstinspires.org/%s/%s" % (
            os.environ.get("FRC_SEASON", "2026"), ev.get("code") or "OTSAN"),
        "venue": ev.get("venue") or "", "city": ev.get("city") or "",
        "season": os.environ.get("FRC_SEASON", "2026"),
        "gameName": "REBUILT presented by Haas",
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataSource": "FRC Events API",
        "isMock": False,
        "counts": {
            "teams": len(teams_out),
            "teamsPlayed": len([t for t in teams_out if t["record"]["w"] + t["record"]["l"] + t["record"]["t"] > 0]),
            "qualPlayed": len(played_qual), "qualTotal": len(qual),
            "playoffPlayed": len([m for m in playoff if m["played"]]),
        },
        "notes": build_notes(playoff, solved),
    }
    matches_out = [{"level": m["level"], "num": m["num"], "red": m["red"], "blue": m["blue"],
                    "redScore": m["redScore"], "blueScore": m["blueScore"]}
                   for m in all_matches if m["played"]]

    out = {
        "meta": meta, "metricGroups": groups_out, "metricDefs": defs_out,
        "teams": teams_out, "rankings": rankings_out(rankings),
        "alliances": (load("alliances") or {}).get("Alliances", []) or [],
        "matches": matches_out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("-" * 60)
    print("Wrote %s" % OUT)
    print("Teams: %d (played %d) | qual: %d/%d | playoff: %d" % (
        meta["counts"]["teams"], meta["counts"]["teamsPlayed"],
        meta["counts"]["qualPlayed"], meta["counts"]["qualTotal"],
        meta["counts"]["playoffPlayed"]))
    print("Metrics solved (%d): %s" % (len(solved), ", ".join(sorted(solved.keys()))))


def team_match_rows(tn, matches):
    rows = []
    for m in matches:
        if not m["played"]:
            continue
        color = "Red" if tn in m["red"] else ("Blue" if tn in m["blue"] else None)
        if not color:
            continue
        own = m["redScore"] if color == "Red" else m["blueScore"]
        opp = m["blueScore"] if color == "Red" else m["redScore"]
        mates = [x for x in (m["red"] if color == "Red" else m["blue"]) if x != tn]
        opps = m["blue"] if color == "Red" else m["red"]
        bd = m["comps"].get(color, {}) or {}
        rows.append({
            "level": "Qualification" if m["level"] == "qual" else "Playoff",
            "num": m["num"], "color": color, "partners": mates, "opponents": opps,
            "allianceScore": own, "oppScore": opp,
            "win": (own is not None and opp is not None and own > opp),
            "breakdown": {k: bd.get(k) for k in ("auto", "teleop", "tower", "fuel") if bd.get(k) is not None},
        })
    return rows


def compute_trends(qual, team_index, metrics):
    out = {mk: {} for mk in metrics}
    played = [m for m in qual if m["played"]]
    if not played:
        return out
    nums = [m["num"] for m in played if m["num"] is not None]
    if not nums:
        return out
    maxk = max(nums)
    seen = {tn: 0 for tn in team_index}
    for k in range(1, maxk + 1):
        for m in played:
            if m["num"] == k:
                for tn in m["red"] + m["blue"]:
                    if tn in seen:
                        seen[tn] += 1
        subset = [m for m in played if m["num"] is not None and m["num"] <= k]
        if len(subset) < 2:
            continue
        for mk in metrics:
            rows = appearances(subset, COMP_METRIC.get(mk, "total"))
            if not has_data(rows):
                continue
            table = solve_opr(rows, team_index, ridge=RIDGE)
            for tn, v in table.items():
                if seen.get(tn, 0) >= 2:
                    out[mk].setdefault(tn, []).append({"m": k, "v": round(v, 1)})
    return out


def rankings_out(rankings):
    return [{"rank": r.get("rank"), "team": r.get("teamNumber"),
             "avgRp": num(r.get("sortOrder1")),
             "w": r.get("wins"), "l": r.get("losses"), "t": r.get("ties"),
             "played": r.get("matchesPlayed")} for r in rankings]


def fmt_dates(ev):
    def d(x):
        return str(x)[:10] if x else ""
    ds, de = d(ev.get("dateStart")), d(ev.get("dateEnd"))
    return ("%s – %s" % (ds, de)) if ds and de else (ds or de)


def build_notes(playoff, solved):
    notes = []
    if not any(m["played"] for m in playoff):
        notes.append("季后赛数据尚未产生或未开始；当前分析基于排位赛。")
    if any(k.startswith("shift") for k in solved):
        notes.append("数据源提供逐班次燃料明细，已计算“分班次 OPR”（转场 + 第1–4班次 + 终局窗口）。")
    notes.append("赛事进行中、样本较少时 OPR 波动较大（并肩作战的队友可能得到相近数值），随比赛增多会趋于稳定。")
    return notes


def inspect_report():
    sj = load("scores_qual")
    keys = []
    if sj:
        for s in (sj.get("MatchScores") or []):
            for a in s.get("alliances", []):
                keys = sorted(a.keys())
                break
            if keys:
                break
    print("=== REBUILT breakdown fields ===")
    print("  " + (", ".join(keys) if keys else "(no scores yet)"))
    print("-" * 60)


if __name__ == "__main__":
    main()
