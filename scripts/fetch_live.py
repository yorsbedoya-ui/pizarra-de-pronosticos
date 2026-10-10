"""Resultados casi en vivo desde el marcador público de ESPN (sin clave).
Descarga todos los partidos de la temporada actual de 8 ligas y guarda
pizarra/data/live/<DIV>.csv con: Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,Status y estadísticas
(HST/AST tiros a puerta, HS/AS tiros, HPoss/APoss posesión, HC/AC córners, HF/AF faltas, HY/AY, HR/AR)
Status: FT (terminado), LIVE (en juego), NS (no empezado).
"""
import csv, json, os, sys, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone

LEAGUES = {"E0": "eng.1", "E1": "eng.2", "SP1": "esp.1", "I1": "ita.1",
           "D1": "ger.1", "F1": "fra.1", "P1": "por.1", "N1": "ned.1"}
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "live")
API = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={d}"

LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); LOG.append(s)

def get(url):
    for i in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pizarra-datos", "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            log("  HTTP", e.code, url, e.read()[:200])
        except Exception as e:
            log("  fallo", url, repr(e)[:200])
        time.sleep(2)
    return None

STATMAP = {"shotsOnTarget": "ST", "totalShots": "S", "possessionPct": "Poss", "wonCorners": "C",
           "foulsCommitted": "F", "yellowCards": "Y", "redCards": "R"}
STATNAMES = set()

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
                       HomeTeam=h["team"]["displayName"], AwayTeam=w["team"]["displayName"],
                       FTHG=h.get("score", "") if status != "NS" else "",
                       FTAG=w.get("score", "") if status != "NS" else "", Status=status)
            # estadísticas reales del partido (si ESPN las publica)
            for side, c in (("H", h), ("A", w)):
                st_ = {s.get("name"): s.get("displayValue") for s in c.get("statistics", []) if s.get("name")}
                STATNAMES.update(st_.keys())
                for key, col in STATMAP.items():
                    if key in st_: row[side + col] = st_[key]
            out.append(row)
        except (KeyError, StopIteration, ValueError) as e:
            log("  evento ignorado:", repr(e)[:120])
    return out

FIELDS = ["Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "Status"] + [s + c for c in STATMAP.values() for s in "HA"]
today = date.today()
season_start = date(today.year if today.month >= 7 else today.year - 1, 7, 20)
os.makedirs(OUT, exist_ok=True)
ok = 0
for div, lg in LEAGUES.items():
    path = os.path.join(OUT, f"{div}.csv")
    old = {}
    if os.path.exists(path):
        rd = csv.DictReader(open(path, encoding="utf-8"))
        if "HST" in (rd.fieldnames or []):  # archivo antiguo sin estadísticas: se recarga entero
            for r in rd:
                old[(r["Date"], r["HomeTeam"], r["AwayTeam"])] = r
    # primera vez: toda la temporada; después: últimos 3 días + próximos 7
    first = (today - timedelta(days=3)) if old else season_start
    d, fails, new = first, 0, 0
    while d <= today + timedelta(days=7):
        js = get(API.format(lg=lg, d=d.strftime("%Y%m%d")))
        if js is None: fails += 1
        for r in parse(js):
            old[(r["Date"], r["HomeTeam"], r["AwayTeam"])] = r; new += 1
        d += timedelta(days=1)
    if old:
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore", restval=""); wr.writeheader()
            wr.writerows(sorted(old.values(), key=lambda r: (r["Date"][6:] + r["Date"][3:5] + r["Date"][:2], r["Time"])))
        ok += 1
    log(div, f"desde {first}:", new, "leídos,", len(old), "en total,", sum(r["Status"] == "FT" for r in old.values()), "terminados,", fails, "días con error")
log("estadísticas disponibles en ESPN:", sorted(STATNAMES))
log("ligas guardadas:", ok, "| hora UTC", datetime.now(timezone.utc).isoformat(timespec="minutes"))
open(os.path.join(OUT, "_registro.txt"), "w").write("\n".join(LOG[-200:]) + "\n")
