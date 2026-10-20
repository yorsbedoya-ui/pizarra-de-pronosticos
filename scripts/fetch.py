"""Descarga datos reales de football-data.co.uk (resultados, tiros, córners, tarjetas y cuotas)
y la lista de próximos partidos con cuotas. Lo ejecuta GitHub Actions cada día.
Salida: data/fd/<temporada>/<liga>.csv y data/fd/fixtures.csv
"""
import os, sys, time, urllib.request
from datetime import date

LEAGUES = ["E0", "E1", "SP1", "I1", "D1", "F1", "P1", "N1", "B1", "SC0", "T1", "G1"]  # las 4 últimas solo alimentan el Elo europeo
BASE = "https://www.football-data.co.uk"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "fd")

def season_codes(n=4):
    t = date.today(); y = t.year if t.month >= 7 else t.year - 1
    return [f"{str(s)[2:]}{str(s+1)[2:]}" for s in range(y - n + 1, y + 1)]

def get(url, dest):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pizarra-datos/1.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
            if len(data) < 200 or b"," not in data[:200]:
                raise ValueError("respuesta vacía o no es CSV")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "wb").write(data)
            return True
        except Exception as e:
            print(f"  intento {attempt+1} falló para {url}: {e}")
            time.sleep(5)
    return False

ok = fail = 0
for s in season_codes():
    for lg in LEAGUES:
        dest = os.path.join(OUT, s, f"{lg}.csv")
        # temporadas cerradas solo se descargan una vez
        if os.path.exists(dest) and s != season_codes()[-1]:
            continue
        if get(f"{BASE}/mmz4281/{s}/{lg}.csv", dest): ok += 1
        else: fail += 1
if get(f"{BASE}/fixtures.csv", os.path.join(OUT, "fixtures.csv")): ok += 1
else: fail += 1

# ---- Ligas "extra" de football-data (formato distinto): Polonia = Ekstraklasa ----
import csv, io
COUNTRY = {"POL": "POLAND", "AUT": "AUSTRIA", "SWZ": "SWITZERLAND", "DNK": "DENMARK", "NOR": "NORWAY", "SWE": "SWEDEN", "ROU": "ROMANIA"}
EXTRA = {"POL": "POL", "AUT": "AUT", "SWZ": "SWZ", "DNK": "DNK", "NOR": "NOR", "SWE": "SWE", "ROU": "ROU"}   # fichero de football-data -> código interno
def season_of(s):  # "2025/2026" -> "2526"; ligas de año natural "2026" -> "2526"
    s = (s or "").strip()
    if "/" in s:
        a, b = s.split("/")[:2]; return a[-2:] + b[-2:]
    if s.isdigit() and len(s) == 4:
        y = int(s); return f"{(y-1)%100:02d}{y%100:02d}"
    return None
STD = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
       "PSCH", "PSCD", "PSCA", "AvgCH", "AvgCD", "AvgCA", "B365CH", "B365CD", "B365CA", "MaxCH", "MaxCD", "MaxCA"]
keep = set(season_codes())
for name, div in EXTRA.items():
    raw = os.path.join(OUT, "_raw", f"{name}.csv")
    if not get(f"{BASE}/new/{name}.csv", raw): fail += 1; continue
    ok += 1
    rows = {}
    for r in csv.DictReader(io.open(raw, encoding="utf-8-sig", errors="replace")):
        s = season_of(r.get("Season", ""))
        if s not in keep: continue
        out = {"Div": div, "Date": r.get("Date", ""), "Time": r.get("Time", ""), "HomeTeam": r.get("Home", ""),
               "AwayTeam": r.get("Away", ""), "FTHG": r.get("HG", ""), "FTAG": r.get("AG", ""), "FTR": r.get("Res", "")}
        for k in STD[8:]: out[k] = r.get(k, "")
        rows.setdefault(s, []).append(out)
    for s, rs in rows.items():
        dest = os.path.join(OUT, s, f"{div}.csv"); os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=STD); w.writeheader(); w.writerows(rs)
        print(f"  {div} {s}: {len(rs)} partidos")
# próximos partidos de las ligas extra, al formato estándar de fixtures.csv
rawf = os.path.join(OUT, "_raw", "new_league_fixtures.csv")
if get(f"{BASE}/new_league_fixtures.csv", rawf):
    ok += 1; fx = []
    for r in csv.DictReader(io.open(rawf, encoding="utf-8-sig", errors="replace")):
        country = r.get("Country", "").strip().upper()
        div = next((d for n, d in EXTRA.items() if r.get("Div", "") == n or country.startswith(COUNTRY.get(n, "?"))), None)
        if not div: continue
        o = {"Div": div, "Date": r.get("Date", ""), "Time": r.get("Time", ""), "HomeTeam": r.get("Home", r.get("HomeTeam", "")),
             "AwayTeam": r.get("Away", r.get("AwayTeam", ""))}
        for k in ("AvgH", "AvgD", "AvgA", "PSH", "PSD", "PSA", "B365H", "B365D", "B365A", "MaxH", "MaxD", "MaxA"):
            o[k] = r.get(k, "")
        fx.append(o)
    with open(os.path.join(OUT, "fixtures_extra.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Div", "Date", "Time", "HomeTeam", "AwayTeam", "AvgH", "AvgD", "AvgA", "PSH", "PSD", "PSA",
                                           "B365H", "B365D", "B365A", "MaxH", "MaxD", "MaxA"]); w.writeheader(); w.writerows(fx)
    print("  próximos partidos extra:", len(fx))
else:
    fail += 1
print(f"Descargados {ok}, fallidos {fail}")
sys.exit(1 if ok == 0 else 0)
