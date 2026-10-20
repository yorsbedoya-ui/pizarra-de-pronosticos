"""Competiciones europeas: probabilidades de ClubElo (escala común para todos los clubes) y
resultados/estadísticas de ESPN. Guarda data/europa/."""
import csv, io, json, os, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "europa"); os.makedirs(OUT, exist_ok=True)
LOG = []
def log(*a): s = " ".join(str(x) for x in a); print(s); LOG.append(s)
def get(url, binary=False):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pizarra-datos"})
            b = urllib.request.urlopen(req, timeout=60).read()
            return b if binary else b.decode("utf-8", "replace")
        except Exception as e:
            log("  fallo", url, repr(e)[:150]); time.sleep(3)
    return None
# 1) ClubElo: próximos partidos con probabilidades
fx = get("http://api.clubelo.com/Fixtures")
if fx:
    open(os.path.join(OUT, "clubelo_fixtures.csv"), "w").write(fx)
    rows = list(csv.DictReader(io.StringIO(fx)))
    log("ClubElo fixtures:", len(rows), "filas; columnas:", list(rows[0].keys())[:8] if rows else None)
    from collections import Counter
    log("  por país/competición:", Counter(r.get("Country") for r in rows).most_common(30))
# 2) ClubElo: ranking actual de todos los clubes
today = date.today().isoformat()
rk = get(f"http://api.clubelo.com/{today}")
if rk:
    open(os.path.join(OUT, "clubelo_ranking.csv"), "w").write(rk)
    log("ClubElo ranking:", rk.count("\n"), "clubes")
open(os.path.join(OUT, "_registro.txt"), "w").write("\n".join(LOG) + "\n")
