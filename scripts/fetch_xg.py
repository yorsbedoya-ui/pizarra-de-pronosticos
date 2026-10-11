"""xG real por partido (Understat, 5 grandes ligas) con el paquete abierto soccerdata.
Guarda data/xg/<DIV>.csv con: date,home,away,hg,ag,hxg,axg
"""
import os, sys, traceback
import soccerdata as sd

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "xg")
LEAGUES = {"E0": "ENG-Premier League", "SP1": "ESP-La Liga", "I1": "ITA-Serie A",
           "D1": "GER-Bundesliga", "F1": "FRA-Ligue 1"}
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
os.makedirs(OUT, exist_ok=True)
log = []
ok = 0
for div, lg in LEAGUES.items():
    try:
        us = sd.Understat(leagues=lg, seasons=SEASONS, no_cache=True)
        df = us.read_team_match_stats().reset_index()
        log.append(f"{div}: columnas {list(df.columns)}")
        cols = {c.lower(): c for c in df.columns}
        pick = lambda *names: next((cols[n] for n in names if n in cols), None)
        m = {"date": pick("date"), "home": pick("home_team"), "away": pick("away_team"),
             "hg": pick("home_goals"), "ag": pick("away_goals"), "hxg": pick("home_xg"), "axg": pick("away_xg")}
        if None in m.values():
            df.head(50).to_csv(os.path.join(OUT, f"{div}_raw.csv"), index=False)
            log.append(f"{div}: faltan columnas {m}"); continue
        out = df[list(m.values())].copy(); out.columns = list(m.keys())
        out = out.dropna(subset=["hxg", "axg"])
        out.to_csv(os.path.join(OUT, f"{div}.csv"), index=False)
        log.append(f"{div}: {len(out)} partidos con xG, último {out['date'].max()}"); ok += 1
    except Exception:
        log.append(f"{div}: ERROR\n" + traceback.format_exc()[-1500:])
open(os.path.join(OUT, "_registro.txt"), "w").write("\n".join(log) + "\n")
print("\n".join(log))
sys.exit(0)
