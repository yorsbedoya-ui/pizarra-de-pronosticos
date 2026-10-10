"""Pizarra de Pronósticos v3 — Dixon-Coles + Elo + tiros a puerta + cuotas del mercado.
Uso:
  python3 -I pronosticos.py <openfootball_dir> <template.html> <salida.html> [AAAA-MM-DD] [--fd <dir data/fd>]
Con --fd usa los CSV de football-data.co.uk (resultados más frescos, tiros y cuotas) del repo de datos.
Sin --fd funciona solo con openfootball (v2). Todo peso de mezcla se elige por backtest walk-forward.
"""
import json, sys, os, math, csv, glob
from datetime import date, timedelta, datetime
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

args = [a for a in sys.argv[1:]]
FD = None
if "--fd" in args:
    i = args.index("--fd"); FD = args[i+1]; del args[i:i+2]
HIST = None   # historial.json: picks publicados (≥85 %) y su resultado real
if "--hist" in args:
    i = args.index("--hist"); HIST = args[i+1]; del args[i:i+2]
HIST_MIN = 0.85
ROOT, TPL, OUT = args[0], args[1], args[2]
TODAY = date.fromisoformat(args[3]) if len(args) > 3 else date.today()
LEAGUES = {"en.1": ("Premier League", "E0"), "es.1": ("LaLiga", "SP1"), "it.1": ("Serie A", "I1"),
           "de.1": ("Bundesliga", "D1"), "fr.1": ("Ligue 1", "F1"), "pt.1": ("Primeira Liga", "P1"),
           "nl.1": ("Eredivisie", "N1"), "en.2": ("Championship", "E1")}
XI, REG, ELO_W, K_ELO, H_ELO = 0.002, 3.0, 0.3, 20, 60
GOAL_W = 0.7          # peso de los goles frente a tiros a puerta (backtest 2025-26: 0.7 mejor que 1.0)
VALUE_EDGE = 0.05     # apuesta de valor: prob. modelo × cuota − 1 ≥ 5 %
G = np.arange(11); TOT = np.add.outer(G, G)
BT_START = TODAY - timedelta(days=280)

# ---------------- Carga de datos ----------------
# fila = (fecha, local, visitante, gl, gv, tiros_puerta_l, tiros_puerta_v, cuotas)
# cuotas = dict(o1, oX, o2, oO, oU) decimales (cierre Pinnacle si existe; si no, media del mercado) o None

def seasons_of():
    y = TODAY.year if TODAY.month >= 7 else TODAY.year - 1
    return y, [f"{s}-{str(s+1)[2:]}" for s in range(y-3, y+1)]

def load_openfootball(code):
    y, ss = seasons_of(); played, fixtures = [], []
    for season in ss:
        p = os.path.join(ROOT, season, code + ".json")
        if not os.path.exists(p): continue
        for m in json.load(open(p))["matches"]:
            sc = m.get("score"); ft = sc.get("ft") if isinstance(sc, dict) else None
            d = date.fromisoformat(m["date"])
            if ft and d < TODAY:
                played.append((d, m["team1"], m["team2"], ft[0], ft[1], None, None, None))
            elif season == ss[-1]:
                fixtures.append(dict(date=d, time=m.get("time", ""), round=m.get("round", ""), h=m["team1"], a=m["team2"], odds=None))
    return sorted(played, key=lambda r: r[0]), fixtures

def pdate(s):
    for f in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try: return datetime.strptime(s.strip(), f).date()
        except ValueError: pass
    return None

def fnum(r, *keys):
    for k in keys:
        try:
            v = float(r.get(k) or "")
            if v > 1.0: return v
        except ValueError: pass
    return None

def odds_of(r, closing=True):
    pre = [("PSCH", "PSCD", "PSCA"), ("AvgCH", "AvgCD", "AvgCA")] if closing else []
    pre += [("PSH", "PSD", "PSA"), ("AvgH", "AvgD", "AvgA"), ("B365H", "B365D", "B365A")]
    o = None
    for k in pre:
        t = [fnum(r, x) for x in k]
        if all(t): o = t; break
    if not o: return None
    ou = [("PC>2.5", "PC<2.5"), ("AvgC>2.5", "AvgC<2.5")] if closing else []
    ou += [("P>2.5", "P<2.5"), ("Avg>2.5", "Avg<2.5"), ("B365>2.5", "B365<2.5")]
    oO = oU = None
    for a, b in ou:
        oO, oU = fnum(r, a), fnum(r, b)
        if oO and oU: break
    return dict(o1=o[0], oX=o[1], o2=o[2], oO=oO, oU=oU)

def load_fd(div):
    played = []
    for p in sorted(glob.glob(os.path.join(FD, "*", f"{div}.csv"))):
        for r in csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")):
            d = pdate(r.get("Date", "")) if r.get("Date") else None
            try: hg, ag = int(r["FTHG"]), int(r["FTAG"])
            except (ValueError, KeyError, TypeError): continue
            if not d or not r.get("HomeTeam"): continue
            hst = fnum(r, "HST"); ast = fnum(r, "AST")
            try: hst, ast = int(r["HST"]), int(r["AST"])
            except (ValueError, KeyError, TypeError): hst = ast = None
            played.append((d, r["HomeTeam"].strip(), r["AwayTeam"].strip(), hg, ag, hst, ast, odds_of(r)))
    fixtures = []
    fp = os.path.join(FD, "fixtures.csv")
    if os.path.exists(fp):
        for r in csv.DictReader(open(fp, encoding="utf-8-sig", errors="replace")):
            if r.get("Div", "").strip() != div: continue
            d = pdate(r.get("Date", ""))
            if d and d >= TODAY:
                fixtures.append(dict(date=d, time=(r.get("Time") or "").strip(), round="Próximos partidos",
                                     h=r["HomeTeam"].strip(), a=r["AwayTeam"].strip(), odds=odds_of(r, closing=False)))
    return sorted(played, key=lambda r: r[0]), fixtures

# ---------------- Resultados en vivo (ESPN) ----------------
import difflib, unicodedata, re as _re
ALIAS = {"manchester city": "man city", "manchester united": "man united", "nottingham forest": "nott'm forest",
         "wolverhampton wanderers": "wolves", "tottenham hotspur": "tottenham", "newcastle united": "newcastle",
         "west ham united": "west ham", "brighton & hove albion": "brighton", "afc bournemouth": "bournemouth",
         "leeds united": "leeds", "sheffield wednesday": "sheffield weds", "sheffield united": "sheffield united",
         "queens park rangers": "qpr", "west bromwich albion": "west brom", "atletico madrid": "ath madrid",
         "athletic club": "ath bilbao", "real sociedad": "sociedad", "celta vigo": "celta", "real betis": "betis",
         "rayo vallecano": "vallecano", "deportivo alaves": "alaves", "espanyol": "espanol", "internazionale": "inter",
         "ac milan": "milan", "as roma": "roma", "hellas verona": "verona", "bayern munich": "bayern munich",
         "borussia dortmund": "dortmund", "bayer leverkusen": "leverkusen", "borussia monchengladbach": "m'gladbach",
         "eintracht frankfurt": "ein frankfurt", "vfb stuttgart": "stuttgart", "fc koln": "fc koln", "mainz": "mainz",
         "paris saint-germain": "paris sg", "olympique de marseille": "marseille", "olympique lyonnais": "lyon",
         "as monaco": "monaco", "stade rennais": "rennes", "sporting cp": "sp lisbon", "sporting": "sp lisbon",
         "sl benfica": "benfica", "fc porto": "porto", "sc braga": "sp braga", "vitoria guimaraes": "guimaraes",
         "psv eindhoven": "psv eindhoven", "az alkmaar": "az alkmaar", "feyenoord rotterdam": "feyenoord",
         "nec nijmegen": "nijmegen", "fc cologne": "fc koln", "1. fc koln": "fc koln", "deportivo": "la coruna", "deportivo la coruna": "la coruna", "racing santander": "santander", "stoke city": "stoke", "hull city": "hull", "fc twente": "twente", "fc utrecht": "utrecht", "go ahead eagles": "go ahead eagles"}

def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    s = ALIAS.get(s, s)
    return _re.sub(r"\b(fc|cf|afc|sc|ac|sv|ssc|ss|us|rc|cd|ud|sd|vfl|vfb|tsg|bv|1\.)\b", " ", s).replace(".", " ").split()

SUFFIX = {"city", "town", "county", "united", "rovers", "athletic", "albion", "wanderers", "fc"}

def name_mapper(known):
    keys = {" ".join(_norm(k)): k for k in known}
    cache = {}
    def f(n):
        if n in cache: return cache[n]
        q = " ".join(_norm(n)); best = keys.get(q)
        if not best:  # sin sufijos genéricos (city, town...) y solo si es único
            strip = lambda s: " ".join(w for w in s.split() if w not in SUFFIX)
            c = [k for k in keys if strip(k) == strip(q) and strip(q)]
            if len(c) == 1: best = keys[c[0]]
        if not best:
            m = difflib.get_close_matches(q, keys.keys(), n=1, cutoff=0.72)
            if not m:  # coincidencia por palabra significativa
                w = [k for k in keys if set(q.split()) & set(k.split()) - {"united", "city", "real", "club", "de"}]
                m = w if len(w) == 1 else []
            best = keys[m[0]] if m else None
        cache[n] = best; return best
    return f

LIVE = None
if FD and os.path.isdir(os.path.join(FD, "..", "live")):
    LIVE = os.path.join(FD, "..", "live")

def merge_live(div, played, fixtures):
    """Añade resultados terminados de ESPN que aún no estén en los datos principales."""
    p = os.path.join(LIVE, f"{div}.csv") if LIVE else None
    if not p or not os.path.exists(p): return played, 0, []
    # orden = prioridad: los nombres de los partidos jugados (misma fuente que las cuotas) ganan
    fdfx = [f for f in fixtures if f["round"] == "Próximos partidos"]  # solo calendario de football-data (mismos nombres)
    known = [f["h"] for f in fdfx] + [f["a"] for f in fdfx] + [r[1] for r in played] + [r[2] for r in played]
    mp = name_mapper(known); have = {(r[0], r[1], r[2]) for r in played}
    last = max((r[0] for r in played), default=date(2000, 1, 1)); add, miss = [], set()
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r.get("Status") != "FT": continue
        d = pdate(r["Date"]); h, a = mp(r["HomeTeam"]), mp(r["AwayTeam"])
        if not h: miss.add(r["HomeTeam"])
        if not a: miss.add(r["AwayTeam"])
        if not (d and h and a) or d <= last - timedelta(days=3) or d >= TODAY: continue
        if any((d + timedelta(days=k), h, a) in have for k in (-1, 0, 1)): continue
        try:
            hst = int(r["HST"]) if r.get("HST") else None; ast_ = int(r["AST"]) if r.get("AST") else None
            add.append((d, h, a, int(r["FTHG"]), int(r["FTAG"]), hst if ast_ is not None else None, ast_ if hst is not None else None, None))
        except ValueError: pass
    return sorted(played + add, key=lambda r: r[0]), len(add), sorted(miss)

# ---------------- Estadísticas reales por partido (football-data + ESPN) ----------------
STAT_COLS = ["HST", "AST", "HS", "AS", "HC", "AC", "HPoss", "APoss", "HY", "AY", "HR", "AR"]

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def match_stats(div, played):
    """Lista de partidos jugados con sus estadísticas reales, nombres de la fuente principal."""
    out = {}
    if FD:
        for p in sorted(glob.glob(os.path.join(FD, "*", f"{div}.csv"))):
            for r in csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")):
                d = pdate(r.get("Date", "")) if r.get("Date") else None
                if not d or not r.get("FTHG") or d >= TODAY: continue
                try: s = dict(date=d, h=r["HomeTeam"].strip(), a=r["AwayTeam"].strip(), hg=int(r["FTHG"]), ag=int(r["FTAG"]))
                except ValueError: continue
                for c in STAT_COLS: s[c] = _num(r.get(c))
                out[(d, s["h"], s["a"])] = s
    lp = os.path.join(LIVE, f"{div}.csv") if LIVE else None
    if lp and os.path.exists(lp):
        mp = name_mapper([r[1] for r in played] + [r[2] for r in played])
        for r in csv.DictReader(open(lp, encoding="utf-8")):
            if r.get("Status") != "FT": continue
            d = pdate(r["Date"]); h, a = mp(r["HomeTeam"]), mp(r["AwayTeam"])
            if not (d and h and a) or d >= TODAY: continue
            key = next(((d + timedelta(days=k), h, a) for k in (0, -1, 1) if (d + timedelta(days=k), h, a) in out), None)
            if key:  # completar lo que falte (p. ej. posesión) sin pisar football-data
                for c in STAT_COLS:
                    if out[key].get(c) is None: out[key][c] = _num(r.get(c))
            else:
                try: s = dict(date=d, h=h, a=a, hg=int(r["FTHG"]), ag=int(r["FTAG"]))
                except ValueError: continue
                for c in STAT_COLS: s[c] = _num(r.get(c))
                out[(d, h, a)] = s
    return sorted(out.values(), key=lambda s: s["date"])

def team_summary(stats, team, k=5):
    """Medias reales de los últimos k partidos de liga del equipo."""
    ms = [s for s in stats if team in (s["h"], s["a"])][-k:]
    if not ms: return None
    acc = {"gf": [], "gc": [], "stf": [], "stc": [], "sf": [], "sc": [], "cf": [], "poss": []}
    for s in ms:
        home = s["h"] == team; me, op = ("H", "A") if home else ("A", "H")
        acc["gf"].append(s["hg"] if home else s["ag"]); acc["gc"].append(s["ag"] if home else s["hg"])
        for key, col, side in (("stf", "ST", me), ("stc", "ST", op), ("sf", "S", me), ("sc", "S", op), ("cf", "C", me), ("poss", "Poss", me)):
            v = s.get(side + col)
            if v is not None: acc[key].append(v)
    avg = lambda v: round(sum(v) / len(v), 1) if v else None
    return dict(n=len(ms), **{key: avg(v) for key, v in acc.items()})

def stat_row(s):
    g = lambda c: (int(s[c]) if s.get(c) is not None and c[-4:] != "Poss" else s.get(c))
    return dict(date=s["date"].isoformat(), h=s["h"], a=s["a"], hg=s["hg"], ag=s["ag"],
                **{c: g(c) for c in ("HST", "AST", "HS", "AS", "HC", "AC", "HPoss", "APoss")})


# ---------------- Tiros esperados en el próximo partido ----------------
# Fuerza de cada equipo (últimos SHOT_K partidos) frente a la media de la liga (últimos SHOT_LG),
# suavizada hacia 1 con SHOT_SH. Ajustes elegidos por backtest con partidos reales de 2026.
from collections import deque, defaultdict
SHOT_K, SHOT_LG, SHOT_SH = 38, 200, 0.6
SHOT_COLS = ("ST", "S", "C")

class ShotState:
    def __init__(self):
        self.team = {c: defaultdict(lambda: deque(maxlen=SHOT_K)) for c in SHOT_COLS}
        self.lg = {c: deque(maxlen=SHOT_LG) for c in SHOT_COLS}
    def proj(self, h, a, c):
        lg = self.lg[c]
        if len(lg) < 50: return None
        lh = sum(x for x, _ in lg) / len(lg); la = sum(y for _, y in lg) / len(lg); lall = (lh + la) / 2
        def tm(t):
            d = self.team[c].get(t)
            if not d or len(d) < 4: return None
            f = sum(x for x, _ in d) / len(d); g = sum(y for _, y in d) / len(d)
            return 1 + SHOT_SH * (f / lall - 1), 1 + SHOT_SH * (g / lall - 1)
        th, ta = tm(h), tm(a)
        if not th or not ta: return None
        return lh * th[0] * ta[1], la * ta[0] * th[1]
    def add(self, s):
        for c in SHOT_COLS:
            x, y = s.get("H" + c), s.get("A" + c)
            if x is None or y is None: continue
            self.lg[c].append((x, y)); self.team[c][s["h"]].append((x, y)); self.team[c][s["a"]].append((y, x))

def shots_run(stats, bt_from):
    """Recorre los partidos en orden: backtest (quién tira más a puerta) y estado final para predecir."""
    st, rec = ShotState(), []
    for s in stats:
        if s["date"] >= bt_from and s.get("HST") is not None:
            p = st.proj(s["h"], s["a"], "ST")
            if p: rec.append((p[0], p[1], s["HST"], s["AST"]))
        st.add(s)
    return st, rec

# ---------------- Modelo ----------------
def fit_poisson(train, ref, x0=None):
    teams = sorted({r[1] for r in train} | {r[2] for r in train}); idx = {t: i for i, t in enumerate(teams)}; n = len(teams)
    hi = np.array([idx[r[1]] for r in train]); ai = np.array([idx[r[2]] for r in train])
    hg = np.array([r[3] for r in train], float); ag = np.array([r[4] for r in train], float)
    has = np.array([r[5] is not None for r in train])
    th, ta = hg.copy(), ag.copy()
    if has.any():
        hs = np.array([r[5] or 0 for r in train], float); as_ = np.array([r[6] or 0 for r in train], float)
        c = (hg[has].sum() + ag[has].sum()) / max(1, hs[has].sum() + as_[has].sum())
        th[has] = GOAL_W*hg[has] + (1-GOAL_W)*c*hs[has]; ta[has] = GOAL_W*ag[has] + (1-GOAL_W)*c*as_[has]
    w = np.exp(-XI * np.array([(ref - r[0]).days for r in train]))
    def f(x):
        att, de, home, mu = x[:n], x[n:2*n], x[2*n], x[2*n+1]
        lh = np.exp(mu + home + att[hi] - de[ai]); la = np.exp(mu + att[ai] - de[hi])
        v = -(w*(th*np.log(lh) - lh + ta*np.log(la) - la)).sum() + REG*(att@att + de@de) + 100*att.sum()**2
        rh = w*(th - lh); ra = w*(ta - la); g = np.zeros_like(x)
        g[:n] = -(np.bincount(hi, rh, n) + np.bincount(ai, ra, n)) + 2*REG*att + 200*att.sum()
        g[n:2*n] = (np.bincount(ai, rh, n) + np.bincount(hi, ra, n)) + 2*REG*de
        g[2*n] = -rh.sum(); g[2*n+1] = -(rh.sum() + ra.sum())
        return v, g
    if x0 is None or len(x0) != 2*n+2:
        x0 = np.zeros(2*n+2); x0[2*n] = .25; x0[2*n+1] = .2
    x = minimize(f, x0, jac=True, method="L-BFGS-B").x
    lh = np.exp(x[2*n+1] + x[2*n] + x[:n][hi] - x[n:2*n][ai]); la = np.exp(x[2*n+1] + x[:n][ai] - x[n:2*n][hi])
    m00 = (hg == 0) & (ag == 0); m01 = (hg == 0) & (ag == 1); m10 = (hg == 1) & (ag == 0); m11 = (hg == 1) & (ag == 1)
    def tll(r):
        t = np.ones_like(lh); t[m00] = 1 - lh[m00]*la[m00]*r; t[m01] = 1 + lh[m01]*r; t[m10] = 1 + la[m10]*r; t[m11] = 1 - r
        return -(w*np.log(np.clip(t, 1e-9, None))).sum()
    rs = np.linspace(-.25, .1, 36); rho = rs[np.argmin([tll(r) for r in rs])]
    return dict(idx=idx, x=x, n=n, rho=rho)

def matrix(P, h, a):
    i, j, n, x = P["idx"][h], P["idx"][a], P["n"], P["x"]
    lh = math.exp(x[2*n+1] + x[2*n] + x[i] - x[n+j]); la = math.exp(x[2*n+1] + x[j] - x[n+i])
    M = np.outer(poisson.pmf(G, lh), poisson.pmf(G, la)); r = P["rho"]
    M[0,0] *= 1 - lh*la*r; M[0,1] *= 1 + lh*r; M[1,0] *= 1 + la*r; M[1,1] *= 1 - r
    return M/M.sum(), lh, la

def elo(rows):
    R, hist = {}, []
    for r in rows:
        h, a, hg, ag = r[1], r[2], r[3], r[4]
        rh, ra = R.get(h, 1500), R.get(a, 1500); hist.append(rh - ra + H_ELO)
        e = 1/(1 + 10**(-(rh - ra + H_ELO)/400)); s = 1 if hg > ag else (.5 if hg == ag else 0)
        gd = abs(hg - ag); mult = 1 if gd <= 1 else (1.5 if gd == 2 else (11 + gd)/8)
        R[h] = rh + K_ELO*mult*(s - e); R[a] = ra - K_ELO*mult*(s - e)
    return R, np.array(hist)

def outc(hg, ag): return 0 if hg > ag else (1 if hg == ag else 2)

def ordlogit(train, hist, ref):
    keep = np.array([(ref - r[0]).days < 730 for r in train])
    d = hist[keep]; o = np.array([outc(r[3], r[4]) for r, k in zip(train, keep) if k])
    w = np.exp(-0.002*np.array([(ref - r[0]).days for r, k in zip(train, keep) if k]))
    def f(p):
        b, c1, g = p; c2 = c1 + math.exp(g)
        pa = 1/(1+np.exp(-(c1 - b*d))); pad = 1/(1+np.exp(-(c2 - b*d)))
        pr = np.where(o == 2, pa, np.where(o == 1, pad - pa, 1 - pad))
        return -(w*np.log(np.clip(pr, 1e-9, 1))).sum()
    return minimize(f, [0.005, -1, 0], method="Nelder-Mead").x

def olpred(p, d):
    b, c1, g = p; c2 = c1 + math.exp(g)
    pa = 1/(1+math.exp(-(c1 - b*d))); pad = 1/(1+math.exp(-(c2 - b*d)))
    return np.array([1 - pad, pad - pa, pa])

def implied(o):
    """Probabilidades del mercado sin margen de la casa."""
    if not o: return None, None
    p = np.array([1/o["o1"], 1/o["oX"], 1/o["o2"]]); p /= p.sum()
    pO = None
    if o.get("oO") and o.get("oU"):
        a, b = 1/o["oO"], 1/o["oU"]; pO = a/(a+b)
    return p, pO

class Model:
    def __init__(self, train, ref, x0=None):
        self.P = fit_poisson(train, ref, x0); self.R, hist = elo(train); self.ol = ordlogit(train, hist, ref)
    def raw(self, h, a):
        if h not in self.P["idx"] or a not in self.P["idx"]: return None
        M, lh, la = matrix(self.P, h, a)
        pp = np.array([np.tril(M, -1).sum(), np.trace(M), np.triu(M, 1).sum()])
        pe = olpred(self.ol, self.R.get(h, 1450) - self.R.get(a, 1450) + H_ELO)
        k = np.dstack(np.unravel_index(np.argsort(-M, axis=None)[:3], M.shape))[0]
        return dict(p=(1 - ELO_W)*pp + ELO_W*pe, o25=float(M[TOT > 2.5].sum()), o15=float(M[TOT > 1.5].sum()),
                    o35=float(M[TOT > 3.5].sum()), btts=float(M[1:, 1:].sum()), lh=lh, la=la,
                    scores=[[int(x), int(y), round(float(M[x, y]), 3)] for x, y in k])

def markets(raw, odds, wm):
    """Mezcla modelo/mercado con peso wm y construye todos los mercados."""
    p, o25 = raw["p"].copy(), raw["o25"]
    pm, pO = implied(odds)
    if pm is not None and wm > 0: p = (1 - wm)*p + wm*pm
    if pO is not None and wm > 0: o25 = (1 - wm)*o25 + wm*pO
    return {"1": p[0], "X": p[1], "2": p[2], "1X": p[0]+p[1], "X2": p[1]+p[2], "12": p[0]+p[2],
            "+1.5": raw["o15"], "+2.5": o25, "-2.5": 1-o25, "+3.5": raw["o35"], "-3.5": 1-raw["o35"],
            "AM-Sí": raw["btts"], "AM-No": 1-raw["btts"]}

def hit(market, hg, ag):
    t = hg + ag; o = outc(hg, ag)
    return {"1": o == 0, "X": o == 1, "2": o == 2, "1X": o != 2, "X2": o != 0, "12": o != 1,
            "+1.5": t > 1.5, "+2.5": t > 2.5, "-2.5": t < 2.5, "-3.5": t < 3.5, "+3.5": t > 3.5,
            "AM-Sí": hg > 0 and ag > 0, "AM-No": not (hg > 0 and ag > 0)}[market]

SAFE = ["1", "2", "1X", "X2", "+2.5", "-2.5", "AM-Sí", "AM-No"]
ODDKEY = {"1": "o1", "X": "oX", "2": "o2", "+2.5": "oO", "-2.5": "oU"}

def values(raw, odds):
    """Mercados donde el modelo propio (sin mezclar) ve más probabilidad que la cuota."""
    if not odds: return []
    mk = markets(raw, None, 0); out = []
    for m, k in ODDKEY.items():
        o = odds.get(k)
        if o and mk[m]*o - 1 >= VALUE_EDGE and mk[m] >= 0.25:
            out.append(dict(m=m, odds=o, p=mk[m], edge=mk[m]*o - 1))
    return sorted(out, key=lambda v: -v["edge"])[:2]

def form(played, team, k=5):
    res = []
    for r in reversed(played):
        if team in (r[1], r[2]):
            gf, ga = (r[3], r[4]) if r[1] == team else (r[4], r[3])
            res.append("V" if gf > ga else ("E" if gf == ga else "D"))
            if len(res) == k: break
    return "".join(res)

# ---------------- Backtest + predicciones ----------------
bt, per_league = [], []
for code, (name, div) in LEAGUES.items():
    src = "openfootball"
    played, fixtures = load_openfootball(code)
    if FD and glob.glob(os.path.join(FD, "*", f"{div}.csv")):
        p2, f2 = load_fd(div)
        # football-data trae tiros y cuotas: se prefiere salvo que vaya más de una semana por detrás
        if p2 and (not played or p2[-1][0] >= played[-1][0] - timedelta(days=7)):
            played, src = p2, "football-data"
            fixtures = f2 or [dict(f, odds=None) for f in fixtures]  # sin fixtures.csv: calendario openfootball (nombres pueden no coincidir)
    played = [r for r in played if r[0] < TODAY]
    if not played: continue
    played, n_live, miss = merge_live(div, played, fixtures)
    if n_live or miss:
        print(f"  {name}: +{n_live} resultados de ESPN" + (f" | sin emparejar: {miss[:6]}" if miss else ""), flush=True)
    if n_live: src += "+espn"
    weeks = sorted({r[0].isocalendar()[:2] for r in played if r[0] >= BT_START})
    x0, lbt = None, []
    for wk in weeks:
        test = [r for r in played if r[0].isocalendar()[:2] == wk]; st = min(r[0] for r in test)
        mdl = Model([r for r in played if r[0] < st], st, x0); x0 = mdl.P["x"]
        for r in test:
            rw = mdl.raw(r[1], r[2])
            if rw: lbt.append(dict(raw=rw, odds=r[7], hg=r[3], ag=r[4], lg=code))
    bt += lbt
    per_league.append(dict(code=code, name=name, src=src, played=played, fixtures=fixtures, n_bt=len(lbt), div=div,
                           stats=match_stats(div, played)))
    print(name, "| fuente", src, "| datos hasta", played[-1][0], "| backtest", len(lbt), flush=True)

# Peso del mercado elegido por backtest (log-loss 1X2) sobre partidos con cuotas
with_odds = [b for b in bt if b["odds"]]
def ll(wm, items):
    return float(np.mean([-math.log(max(1e-9, markets(b["raw"], b["odds"], wm)[("1", "X", "2")[outc(b["hg"], b["ag"])]])) for b in items]))
WM, mkt_test = 0.0, None
if len(with_odds) >= 300:
    grid = [0, .2, .4, .5, .6, .7, .8, .9, 1.0]
    scores = {w: ll(w, with_odds) for w in grid}; WM = min(scores, key=scores.get)
    mkt_test = dict(n=len(with_odds), grid={str(k): round(v, 4) for k, v in scores.items()}, chosen=WM)
    print("Peso mercado:", mkt_test, flush=True)

leagues = []
SHOT_BT = []
for L in per_league:
    played = L["played"]; mdl = Model(played, TODAY)
    up = sorted([f for f in L["fixtures"] if f["date"] >= TODAY], key=lambda f: (f["date"], f["time"]))
    if up and up[0]["round"] != "Próximos partidos":
        up = [f for f in up if f["round"] == up[0]["round"]]
    else:
        up = [f for f in up if f["date"] <= up[0]["date"] + timedelta(days=6)] if up else []
    preds = []; smp = name_mapper([s["h"] for s in L["stats"]] + [s["a"] for s in L["stats"]])
    sstate, srec = shots_run(L["stats"], BT_START); SHOT_BT.extend(srec)
    for f in up:
        rw = mdl.raw(f["h"], f["a"])
        if not rw: continue
        mk = markets(rw, f["odds"], WM); safe = max(SAFE, key=lambda k: mk[k])
        preds.append(dict(date=f["date"].isoformat(), time=f["time"], round=f["round"], h=f["h"], a=f["a"],
                          fh=form(played, f["h"]), fa=form(played, f["a"]), lh=round(rw["lh"], 2), la=round(rw["la"], 2),
                          mk={k: round(v, 3) for k, v in mk.items()}, scores=rw["scores"], safe=safe,
                          odds=f["odds"], value=[dict(v, p=round(v["p"], 3), edge=round(v["edge"], 3)) for v in values(rw, f["odds"])],
                          sh=team_summary(L["stats"], smp(f["h"]) or f["h"]), sa=team_summary(L["stats"], smp(f["a"]) or f["a"]),
                          shots={c: [round(v, 1) for v in pr] for c in SHOT_COLS
                                 for pr in [sstate.proj(smp(f["h"]) or f["h"], smp(f["a"]) or f["a"], c)] if pr}))
    lb = [b for b in bt if b["lg"] == L["code"]]
    acc = float(np.mean([hit(max("1X2", key=lambda k: m[k]), b["hg"], b["ag"]) for b in lb for m in [markets(b["raw"], b["odds"], WM)]])) if lb else None
    leagues.append(dict(code=L["code"], name=L["name"], src=L["src"], last_data=played[-1][0].isoformat(), n_bt=L["n_bt"],
                        acc=round(acc, 3) if acc is not None else None, matches=preds,
                        recent=[stat_row(s) for s in L["stats"] if s["date"] >= TODAY - timedelta(days=4)][::-1]))

def band_stats(items):
    bands = [(0, .45), (.45, .55), (.55, .65), (.65, .75), (.75, .85), (.85, 1.01)]
    out = []
    for lo, hi_ in bands:
        s = [(p, h) for p, h in items if lo <= p < hi_]
        if s: out.append(dict(lo=lo, hi=min(hi_, 1), n=len(s), pred=round(float(np.mean([p for p, _ in s])), 3), real=round(float(np.mean([h for _, h in s])), 3)))
    return out
def thr(items, t):
    s = [h for p, h in items if p >= t]; return dict(n=len(s), real=round(float(np.mean(s)), 3) if s else None)

MK = [markets(b["raw"], b["odds"], WM) for b in bt]
win = [(max(m[k] for k in "1X2"), hit(max("1X2", key=lambda k: m[k]), b["hg"], b["ag"])) for m, b in zip(MK, bt)]
safe = [(m[s], hit(s, b["hg"], b["ag"])) for m, b in zip(MK, bt) for s in [max(SAFE, key=lambda k: m[k])]]
o25 = [hit("+2.5" if m["+2.5"] >= .5 else "-2.5", b["hg"], b["ag"]) for m, b in zip(MK, bt)]
# ROI real de las apuestas de valor (1 unidad por apuesta, a la cuota de cierre)
vb = [(v, b) for b in bt for v in values(b["raw"], b["odds"])]
value_bt = None
if vb:
    prof = [(v["odds"] - 1) if hit(v["m"], b["hg"], b["ag"]) else -1 for v, b in vb]
    value_bt = dict(n=len(vb), hit=round(float(np.mean([p > 0 for p in prof])), 3), roi=round(float(np.mean(prof)), 3))
    if value_bt["roi"] < 0:  # si históricamente pierden dinero, no se muestran
        for l in leagues:
            for m in l["matches"]: m["value"] = []
def shot_summary(rec):
    if not rec: return None
    v = np.array(rec); eh, ea, rh, ra = v.T
    out = dict(n=len(v), mae=round(float(np.mean(np.abs(np.r_[eh, ea] - np.r_[rh, ra]))), 2), bands=[])
    for lo, hi_ in ((0, 1), (1, 1.5), (1.5, 2.5), (2.5, 99)):
        m = (rh != ra) & (np.abs(eh - ea) >= lo) & (np.abs(eh - ea) < hi_)
        if m.sum() >= 20:
            out["bands"].append(dict(lo=lo, hi=hi_, n=int(m.sum()), real=round(float(np.mean((eh > ea)[m] == (rh > ra)[m])), 3)))
    return out

summary = dict(n=len(bt), from_=BT_START.isoformat(), shots=shot_summary(SHOT_BT), market_weight=WM, market_test=mkt_test, value=value_bt,
               acc=round(float(np.mean([h for _, h in win])), 3), o25=round(float(np.mean(o25)), 3),
               win65=thr(win, .65), safe80=thr(safe, .80), safe85=thr(safe, .85),
               cal_win=band_stats(win), cal_safe=band_stats(safe))
# ---------------- Historial real (picks publicados en vivo) ----------------
hist_out = None
if HIST:
    try: H = json.load(open(HIST))
    except (OSError, ValueError): H = []
    seen = {e["id"] for e in H}
    for l in leagues:
        for m in l["matches"]:
            p = m["mk"][m["safe"]]; hid = f'{m["date"]}|{m["h"]}|{m["a"]}'
            if p >= HIST_MIN and hid not in seen:
                H.append(dict(id=hid, lg=l["code"], liga=l["name"], date=m["date"], h=m["h"], a=m["a"], m=m["safe"],
                              p=round(p, 3), pub=TODAY.isoformat(), res=None, hit=None)); seen.add(hid)
    played_by, mappers = {}, {}
    for L in per_league:
        played_by[L["code"]] = {(r[0].isoformat(), r[1], r[2]): (r[3], r[4]) for r in L["played"]}
        mappers[L["code"]] = name_mapper([r[1] for r in L["played"]] + [r[2] for r in L["played"]])
    for e in H:
        if e["res"] is None:
            mp = mappers.get(e["lg"], lambda x: x)
            sc = played_by.get(e["lg"], {}).get((e["date"], e["h"], e["a"])) or \
                 played_by.get(e["lg"], {}).get((e["date"], mp(e["h"]) or e["h"], mp(e["a"]) or e["a"]))
            if sc: e["res"] = f"{sc[0]}-{sc[1]}"; e["hit"] = bool(hit(e["m"], sc[0], sc[1]))
    json.dump(H, open(HIST, "w"), ensure_ascii=False, indent=0)
    done = [e for e in H if e["hit"] is not None]
    hist_out = dict(total=len(H), done=len(done), hits=sum(e["hit"] for e in done),
                    since=min((e["pub"] for e in H), default=TODAY.isoformat()),
                    items=sorted(H, key=lambda e: e["date"], reverse=True)[:40])
    print("Historial:", {k: v for k, v in hist_out.items() if k != "items"}, flush=True)

src = sorted({l["src"] for l in leagues})
try:
    from zoneinfo import ZoneInfo
    _now = datetime.now(ZoneInfo("Europe/Warsaw"))
except Exception:
    _now = datetime.utcnow()
data = dict(generated=TODAY.isoformat(), updated_at=_now.strftime("%Y-%m-%dT%H:%M"), sources=src,
            model="Dixon-Coles + Elo" + (" + tiros" if "football-data" in src else "") + (f" + mercado {int(WM*100)} %" if WM else ""),
            backtest=summary, leagues=leagues, history=hist_out)
print(json.dumps({k: v for k, v in summary.items() if not k.startswith("cal")}, indent=1))
open(OUT, "w").write(open(TPL).read().replace("__DATA__", json.dumps(data, ensure_ascii=False)))
