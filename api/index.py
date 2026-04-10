import re
import json
import requests
from urllib.parse import urlparse, parse_qs

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://understat.com/",
}

UNDERSTAT_BASE = "https://understat.com"

LEAGUE_SLUGS = {
    "Premier League":   "EPL",
    "Bundesliga":       "Bundesliga",
    "La Liga":          "La_liga",
    "Serie A":          "Serie_A",
    "Ligue 1":          "Ligue_1",
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
        return {"error": f"Competition not supported: {competition}"}

    r = requests.get(f"{UNDERSTAT_BASE}/league/{slug}", headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return {"error": f"Understat league fetch failed: {r.status_code}"}

    teams_data = _get_json_from_script(r.text, "teamsData")
    if not teams_data:
        return {"error": "Could not parse teamsData"}

    team_id    = None
    team_title = None
    for tid, tdata in teams_data.items():
        if team_name.lower() in tdata.get("title", "").lower():
            team_id    = tid
            team_title = tdata.get("title", "")
            break

    if not team_id:
        return {"error": f"Team not found: {team_name}"}

    season    = _current_season()
    safe_name = team_title.replace(" ", "_")
    r2 = requests.get(
        f"{UNDERSTAT_BASE}/team/{safe_name}/{season}",
        headers=HEADERS,
        timeout=20,
    )
    if r2.status_code != 200:
        return {"error": f"Understat team fetch failed: {r2.status_code}"}

    dates_data = _get_json_from_script(r2.text, "datesData")
    if not dates_data:
        return {"error": "Could not parse datesData"}

    played = [m for m in dates_data if m.get("isResult")]
    recent = played[-recent_n:] if len(played) >= recent_n else played

    if not recent:
        return {"error": "No recent matches found"}

    xg_for_list = []
    xg_ag_list  = []
    shots_list  = []
    shots_ag    = []
    goals_list  = []
    goals_ag    = []

    for m in recent:
        is_home = m.get("h", {}).get("id") == team_id
        side    = "h" if is_home else "a"
        opp     = "a" if is_home else "h"

        xg_for_list.append(float(m.get("xG",    {}).get(side, 0) or 0))
        xg_ag_list.append( float(m.get("xG",    {}).get(opp,  0) or 0))
        goals_list.append( int(  m.get("goals",  {}).get(side, 0) or 0))
        goals_ag.append(   int(  m.get("goals",  {}).get(opp,  0) or 0))
        shots_list.append( int(  m.get("shots",  {}).get(side, 0) or 0))
        shots_ag.append(   int(  m.get("shots",  {}).get(opp,  0) or 0))

    n           = len(recent)
    total_xg    = sum(xg_for_list)
    total_goals = sum(goals_list)
    total_shots = sum(shots_list)

    return {
        "understat_xG_avg":       round(total_xg / n, 2),
        "understat_xGA_avg":      round(sum(xg_ag_list) / n, 2),
        "understat_shots_avg":    round(total_shots / n, 2),
        "understat_shots_ag_avg": round(sum(shots_ag) / n, 2),
        "understat_gf_avg":       round(total_goals / n, 2),
        "understat_ga_avg":       round(sum(goals_ag) / n, 2),
        "understat_goals_vs_xg":  round(total_goals - total_xg, 2),
        "understat_xg_per_shot":  round(total_xg / total_shots, 3) if total_shots else None,
        "understat_conv_pct":     round((total_goals / total_shots) * 100, 1) if total_shots else None,
        "understat_matches":      n,
    }


def app(request):
    """Vercel serverless function entry point."""
    params      = request.args
    team        = params.get("team", "")
    competition = params.get("competition", "")
    recent_n    = int(params.get("recent_n", 6))

    if not team or not competition:
        return {"error": "team and competition parameters required"}, 400

    result = get_team_stats(team, competition, recent_n)
    return result, 200
