"""Descarga datos reales de football-data.co.uk (resultados, tiros, córners, tarjetas y cuotas)
y la lista de próximos partidos con cuotas. Lo ejecuta GitHub Actions cada día.
Salida: data/fd/<temporada>/<liga>.csv y data/fd/fixtures.csv
"""
import os, sys, time, urllib.request
from datetime import date

LEAGUES = ["E0", "E1", "SP1", "I1", "D1", "F1", "P1", "N1"]
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
print(f"Descargados {ok}, fallidos {fail}")
sys.exit(1 if ok == 0 else 0)
