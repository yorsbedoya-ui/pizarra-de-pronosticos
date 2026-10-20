"""Competiciones europeas (resultados, estadísticas y calendario) desde el marcador público de ESPN.
Guarda data/europa/<COMP>.csv con el mismo formato que data/live/.
Primera vez: desde julio de 2023; después: últimos 4 días + próximos 10."""
import csv, json, os, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "europa"); os.makedirs(OUT, exist_ok=True)
COMPS = {"UCL": "uefa.champions", "UEL": "uefa.europa", "UECL": "uefa.europa.conf"}
API = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={d}"
STATMAP = {"shotsOnTarget": "ST", "totalShots": "S", "possessionPct": "Poss", "wonCorners": "C"}
FIELDS = ["Date", "Time", "Round", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "Status", "HST", "AST", "HS", "AS", "HPoss", "APoss", "HC", "AC"]
LOG = []
def log(*a): s = " ".join(str(x) for x in a); print(s); LOG.append(s)
def get(url):
    for i in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pizarra-datos", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 400: return {"events": []}   # día sin partidos / fuera de temporada
            log("  HTTP", e.code, url)
        except Exception as e:
            log("  fallo", url, repr(e)[:120])
        time.sleep(1)
    return None
def parse(js):
    out = []
    for ev in (js or {}).get("events", []):
        try:
            comp = ev["competitions"][0]
            h = next(c for c in comp["competitors"] if c["homeAway"] == "home")
            w = next(c for c in comp["competitors"] if c["homeAway"] == "away")
            dt = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
            st = comp["status"]["type"]
            status = "FT" if st.get("completed") else ("LIVE" if st.get("state") == "in" else "NS")
            row = dict(Date=dt.strftime("%d/%m/%Y"), Time=dt.strftime("%H:%M"),
                       Round=(ev.get("season", {}) or {}).get("slug", "") or "",
                       HomeTeam=h["team"]["displayName"], AwayTeam=w["team"]["displayName"],
                       FTHG=h.get("score", "") if status != "NS" else "", FTAG=w.get("score", "") if status != "NS" else "", Status=status)
            for side, c in (("H", h), ("A", w)):
                st_ = {s.get("name"): s.get("displayValue") for s in c.get("statistics", []) if s.get("name")}
                for k, col in STATMAP.items():
                    if k in st_: row[side + col] = st_[k]
            out.append(row)
        except (KeyError, StopIteration, ValueError) as e:
            log("  evento ignorado:", repr(e)[:100])
    return out
today = date.today()
for code, lg in COMPS.items():
    path = os.path.join(OUT, f"{code}.csv"); old = {}
    if os.path.exists(path):
        for r in csv.DictReader(open(path, encoding="utf-8")): old[(r["Date"], r["HomeTeam"], r["AwayTeam"])] = r
    first = (today - timedelta(days=4)) if old else date(2023, 7, 1)
    d, n, fails = first, 0, 0
    while d <= today + timedelta(days=10):
        if d.month in (6,) and not old: d += timedelta(days=1); continue   # junio: sin partidos
        js = get(API.format(lg=lg, d=d.strftime("%Y%m%d")))
        if js is None: fails += 1
        for r in parse(js): old[(r["Date"], r["HomeTeam"], r["AwayTeam"])] = r; n += 1
        d += timedelta(days=1)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", restval=""); w.writeheader()
        w.writerows(sorted(old.values(), key=lambda r: (r["Date"][6:] + r["Date"][3:5] + r["Date"][:2], r["Time"])))
    log(code, f"desde {first}:", n, "leídos,", len(old), "en total,", sum(r["Status"] == "FT" for r in old.values()), "terminados,", fails, "días con error")
open(os.path.join(OUT, "_registro.txt"), "w").write("\n".join(LOG[-200:]) + "\n")
