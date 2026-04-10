import re
import json
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://understat.com/",
}

UNDERSTAT_BASE = "https://understat.com"

LEAGUE_SLUGS = {
    "Premier League": "EPL",
    "Bundesliga":     "Bundesliga",
    "La Liga":        "La_liga",
    "Serie A":        "Serie_A",
    "Ligue 1":        "Ligue_1",
    "Champions League": None,
}


def _get_json_from_script(html, var_name):
    pattern = rf"var {var_name}\s*=\s*JSON\.parse\('(.+?)'\)"
    match = re.search(pattern, html)
    if not match:
        return None
    try:
        raw = match.group(1).encode().decode("unicode_escape")
        return json.loads(raw)
    except Exception:
        return None


def _current_season():
    from datetime import date
    today = date.today()
    return str(today.year) if today.month >= 7 else str(today.year - 1)


def get_team_stats(team_name, competition, recent_n=6):
    slug = LEAGUE_SLUGS.get(competition)
    if not slug:
        return {}

    # Get league page
    r = requests.get(f"{UNDERSTAT_BASE}/league/{slug}", headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return {}

    teams_data = _get_json_from_script(r.text, "teamsData")
    if not teams_data:
        return {}

    # Find team
    team_id   = None
    team_title = None
    for tid, tdata in teams_data.items():
        if team_name.lower() in tdata.get("title", "").lower():
            team_id    = tid
            team_title = tdata.get("title", "")
            break

    if not team_id:
        return {}

    # Get team page
    season    = _current_season()
    safe_name = team_title.replace(" ", "_")
    r2 = requests.get(
        f"{UNDERSTAT_BASE}/team/{safe_name}/{season}",
        headers=HEADERS,
        timeout=20,
    )
    if r2.status_code != 200:
        return {}

    dates_data = _get_json_from_script(r2.text, "datesData")
    if not dates_data:
        return {}

    played = [m for m in dates_data if m.get("isResult")]
    recent = played[-recent_n:] if len(played) >= recent_n else played

    if not recent:
        return {}

    stats = {
        "xG_for_list":   [],
        "xG_ag_list":    [],
        "shots_list":    [],
        "shots_ag_list": [],
        "goals_list":    [],
        "goals_ag_list": [],
    }

    for m in recent:
        is_home = m.get("h", {}).get("id") == team_id
        side    = "h" if is_home else "a"
        opp     = "a" if is_home else "h"

        xg_for = float(m.get("xG",    {}).get(side, 0) or 0)
        xg_ag  = float(m.get("xG",    {}).get(opp,  0) or 0)
        gf     = int(m.get("goals",   {}).get(side, 0) or 0)
        ga     = int(m.get("goals",   {}).get(opp,  0) or 0)
        sh     = int(m.get("shots",   {}).get(side, 0) or 0)
        sh_ag  = int(m.get("shots",   {}).get(opp,  0) or 0)

        stats["xG_for_list"].append(xg_for)
        stats["xG_ag_list"].append(xg_ag)
        stats["shots_list"].append(sh)
        stats["shots_ag_list"].append(sh_ag)
        stats["goals_list"].append(gf)
        stats["goals_ag_list"].append(ga)

    n = len(recent)
    xg_avg    = round(sum(stats["xG_for_list"]) / n, 2)
    xga_avg   = round(sum(stats["xG_ag_list"])  / n, 2)
    shots_avg = round(sum(stats["shots_list"])   / n, 2)
    sh_ag_avg = round(sum(stats["shots_ag_list"])/ n, 2)
    gf_avg    = round(sum(stats["goals_list"])   / n, 2)
    ga_avg    = round(sum(stats["goals_ag_list"])/ n, 2)

    total_xg    = sum(stats["xG_for_list"])
    total_goals = sum(stats["goals_list"])
    total_shots = sum(stats["shots_list"])

    return {
        "understat_xG_avg":       xg_avg,
        "understat_xGA_avg":      xga_avg,
        "understat_shots_avg":    shots_avg,
        "understat_shots_ag_avg": sh_ag_avg,
        "understat_gf_avg":       gf_avg,
        "understat_ga_avg":       ga_avg,
        "understat_goals_vs_xg":  round(total_goals - total_xg, 2),
        "understat_xg_per_shot":  round(total_xg / total_shots, 3) if total_shots else None,
        "understat_conv_pct":     round((total_goals / total_shots) * 100, 1) if total_shots else None,
        "understat_matches":      n,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        team        = params.get("team",        [""])[0]
        competition = params.get("competition", [""])[0]
        recent_n    = int(params.get("recent_n", ["6"])[0])

        if not team or not competition:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "team and competition required"}')
            return

        result = get_team_stats(team, competition, recent_n)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
