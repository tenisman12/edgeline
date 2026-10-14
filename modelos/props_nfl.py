# -*- coding: utf-8 -*-
"""
modelos/props_nfl.py - props de jugador y total de equipo en NFL.

Mercados (los mas apostados):
  QB:      yardas de pase, intentos, completos, TD de pase, intercepciones, yardas por tierra del QB
  RB:      yardas por tierra, acarreos, yardas por tierra + recepcion
  WR/TE/RB: yardas de recepcion, recepciones
  Todos:   anytime TD (TD por tierra o recepcion)
  Equipo:  total de puntos del equipo

Metodo (volumen x eficiencia, todo as-of: cada fila solo ve juegos anteriores):
  - Promedios ponderados del jugador (EWMA, vida media 3 juegos, cruza temporadas), promedio de la temporada,
    ultimos 3, uso (target share, air yards share), volumen del equipo (intentos de pase, acarreos).
  - Rival: lo que permite por juego al grupo de posicion (EWMA vida media 4).
  - Contexto de mercado: puntos implicitos del equipo (total y spread de cierre de nflverse), local, domo, viento.
  - Gradient boosting por mercado (Poisson en conteos, cuadratico en yardas, clasificador en anytime TD).
  - Distribucion: residuos fuera de muestra (por temporada) escalados a la proyeccion, por quintil de proyeccion.
    TD de pase, intercepciones: Poisson con la media proyectada.

Validacion (walk-forward por temporada, protocolo del repo): linea de prueba = promedio EWMA del jugador
redondeado a .5 (aproxima la linea de la casa; NO es la linea real). Base = tasa historica de Over contra esa
linea. Publicable si n>=300, mejora la base (Brier) con z>=2.0 en ambas mitades y |p media - tasa real|<=0.04.
Total de equipo: base = puntos implicitos del mercado (esa si es la linea real de cierre).

Datos: nflverse (stats_player_week_<año>.csv y schedules/games.csv). Se bajan a data_maestra/nflverse/ (no se suben).

Uso:
  python modelos/props_nfl.py --validar            # backtest 2022-2025 -> salida/validacion_props_nfl.json
  python modelos/props_nfl.py --partido 2026_06_SEA_DEN [--viento_kmh 10.5] [--fuera "Zach Charbonnet,..."]
                                                    # -> salida/props_nfl.json
  Lineas reales de casas (opcional): --lineas semillas/lineas_props_nfl/<game_id>.json
    [{"jugador": "...", "mercado": "rec_yds", "linea": 91.5, "over": -114, "under": -106, "casa": "..."}]
  EV: p_final = mercado sin vig + 0.35 del modelo en logit (props sin CLV medido); ev_modelo_puro es contexto.
"""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, json, math, os, subprocess, datetime as dt
import numpy as np
import pandas as pd
from scipy import stats as st
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.linear_model import Ridge

REPO = os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "data_maestra", "nflverse")
REL = "https://github.com/nflverse/nflverse-data/releases/download"
ANIOS = list(range(2016, 2027))

STATS = ["attempts", "completions", "passing_yards", "passing_tds", "passing_interceptions", "carries",
         "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
         "target_share", "air_yards_share", "rush_rec_yds", "td_total"]

# mercado -> (columna objetivo, tipo, filtro de rol, nombre)
MERCADOS = {
    "pase_yds":    ("passing_yards", "yds", "qb", "Yardas de pase"),
    "pase_att":    ("attempts", "cnt", "qb", "Intentos de pase"),
    "pase_cmp":    ("completions", "cnt", "qb", "Pases completos"),
    "pase_td":     ("passing_tds", "pois", "qb", "TD de pase"),
    "pase_int":    ("passing_interceptions", "pois", "qb", "Intercepciones"),
    "qb_rush_yds": ("rushing_yards", "yds", "qb", "Yardas por tierra (QB)"),
    "rush_yds":    ("rushing_yards", "yds", "rb", "Yardas por tierra"),
    "rush_att":    ("carries", "cnt", "rb", "Acarreos"),
    "rush_rec_yds": ("rush_rec_yds", "yds", "rb", "Yardas tierra + recepcion"),
    "rec_yds":     ("receiving_yards", "yds", "rec", "Yardas de recepcion"),
    "rec":         ("receptions", "cnt", "rec", "Recepciones"),
    "anytime_td":  ("td_any", "bin", "td", "Anytime TD"),
}


# ---------------------------------------------------------------- datos
def _bajar(nombre, url, refrescar=False):
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, nombre)
    if refrescar or not os.path.exists(ruta) or os.path.getsize(ruta) < 1000:
        subprocess.run(["curl", "-sSL", "--max-time", "180", "-o", ruta, url], check=True)
    return ruta


def cargar(refrescar_actual=True):
    hoy = dt.date.today().year
    partes = []
    for a in ANIOS:
        r = _bajar(f"stats_player_week_{a}.csv", f"{REL}/stats_player/stats_player_week_{a}.csv",
                   refrescar=refrescar_actual and a >= hoy)
        partes.append(pd.read_csv(r, low_memory=False))
    p = pd.concat(partes, ignore_index=True)
    g = pd.read_csv(_bajar("games.csv", f"{REL}/schedules/games.csv", refrescar=refrescar_actual), low_memory=False)
    return p, g


def preparar(p, g):
    p = p[p.season_type.isin(["REG", "POST"]) & p.player_id.notna()].copy()
    for c in STATS[:14]:
        if c not in p:
            p[c] = 0.0
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0.0)
    p["rush_rec_yds"] = p.rushing_yards + p.receiving_yards
    p["td_total"] = p.rushing_tds + p.receiving_tds
    p["td_any"] = (p.td_total >= 1).astype(float)
    g = g.copy()
    g["fecha"] = pd.to_datetime(g.gameday)
    gg = g[["game_id", "fecha", "home_team", "away_team", "home_score", "away_score", "spread_line", "total_line",
            "roof", "wind"]]
    p = p.merge(gg, on="game_id", how="left")
    p = p[p.fecha.notna()].copy()
    p["local"] = (p.team == p.home_team).astype(float)
    return p, g


def tabla_equipos(g, p):
    """Una fila por equipo-juego: puntos, implicitos, volumen y lo que permitio por grupo de posicion."""
    filas = []
    for _, r in g.iterrows():
        if pd.isna(r.spread_line) or pd.isna(r.total_line):
            continue
        for lado, eq, rv, pts, pts_c in (("h", r.home_team, r.away_team, r.home_score, r.away_score),
                                         ("a", r.away_team, r.home_team, r.away_score, r.home_score)):
            imp = r.total_line / 2 + (r.spread_line / 2 if lado == "h" else -r.spread_line / 2)
            filas.append({"game_id": r.game_id, "season": r.season, "fecha": pd.to_datetime(r.gameday), "team": eq,
                          "opp": rv, "local": 1.0 if lado == "h" else 0.0, "pts": pts, "pts_contra": pts_c,
                          "implicito": imp, "spread_eq": r.spread_line if lado == "h" else -r.spread_line,
                          "total_line": r.total_line,
                          "domo": 1.0 if str(r.roof) in ("dome", "closed") else 0.0,
                          "viento": 0.0 if str(r.roof) in ("dome", "closed") else (r.wind if pd.notna(r.wind) else np.nan)})
    t = pd.DataFrame(filas)
    # volumen ofensivo por equipo-juego y lo permitido por posicion (desde los jugadores)
    agg = p.groupby(["game_id", "team"]).agg(t_att=("attempts", "sum"), t_car=("carries", "sum"),
                                              t_pyds=("passing_yards", "sum"), t_ryds=("rushing_yards", "sum")).reset_index()
    pos = p[p.position.isin(["WR", "TE", "RB"])].pivot_table(index=["game_id", "team"], columns="position",
                                                             values="receiving_yards", aggfunc="sum").reset_index()
    pos.columns = ["game_id", "team"] + [f"recyds_{c}" for c in pos.columns[2:]]
    agg = agg.merge(pos, on=["game_id", "team"], how="left")
    t = t.merge(agg, on=["game_id", "team"], how="left")
    t = t.sort_values(["team", "fecha"]).reset_index(drop=True)
    # as-of del equipo (lo suyo) y del rival (lo que permite)
    of_cols = ["pts", "t_att", "t_car", "t_pyds", "t_ryds"]
    sh = t.groupby("team")[of_cols].shift()
    ew = sh.groupby(t.team).ewm(halflife=4, min_periods=1).mean().reset_index(level=0, drop=True)
    for c in of_cols:
        t[f"eq_{c}"] = ew[c]  # alineado por indice
    # lo que permite: las ofensivas del rival en ese juego, as-of sobre la defensa
    perm = t[["game_id", "team"] + of_cols + ["recyds_WR", "recyds_TE", "recyds_RB"]].rename(columns={"team": "opp"})
    perm.columns = ["game_id", "opp"] + [f"perm_{c}" for c in of_cols + ["recyds_WR", "recyds_TE", "recyds_RB"]]
    d = t[["game_id", "team", "fecha"]].merge(perm, left_on=["game_id", "team"], right_on=["game_id", "opp"], how="left")
    # d.team = la defensa; d.perm_* = lo que le hicieron a esa defensa en ese juego
    d = d.drop(columns="opp").sort_values(["team", "fecha"])
    pc = [c for c in d.columns if c.startswith("perm_")]
    shd = d.groupby("team")[pc].shift()
    ewd = shd.groupby(d.team).ewm(halflife=4, min_periods=1).mean().reset_index(level=0, drop=True)
    for c in pc:
        d[f"def_{c[5:]}"] = ewd[c]
    d = d[["game_id", "team"] + [f"def_{c[5:]}" for c in pc]].rename(columns={"team": "opp"})
    t = t.merge(d, on=["game_id", "opp"], how="left")
    return t


def features_jugador(p, t):
    p = p.sort_values(["player_id", "fecha"]).reset_index(drop=True)
    sh = p.groupby("player_id")[STATS].shift()
    ew = sh.groupby(p.player_id).ewm(halflife=3, min_periods=1).mean().reset_index(level=0, drop=True)
    l3 = sh.groupby(p.player_id).rolling(3, min_periods=1).mean().reset_index(level=0, drop=True)
    shs = p.groupby(["player_id", "season"])[STATS].shift()
    ms = shs.groupby([p.player_id, p.season]).expanding().mean().reset_index(level=[0, 1], drop=True)
    for c in STATS:
        p[f"ew_{c}"] = ew[c]
        p[f"l3_{c}"] = l3[c]
        p[f"ms_{c}"] = ms[c]
    p["n_prev"] = p.groupby("player_id").cumcount()
    p["n_temp"] = p.groupby(["player_id", "season"]).cumcount()
    p["dias_desc"] = p.groupby("player_id").fecha.diff().dt.days.clip(upper=300)
    tc = [c for c in t.columns if c.startswith(("eq_", "def_"))] + ["implicito", "spread_eq", "total_line", "domo", "viento"]
    p = p.drop(columns=[c for c in tc if c in p.columns]).merge(t[["game_id", "team"] + tc], on=["game_id", "team"], how="left")
    p["pos_qb"] = (p.position == "QB").astype(float)
    p["pos_rb"] = (p.position == "RB").astype(float)
    p["pos_wr"] = (p.position == "WR").astype(float)
    p["pos_te"] = (p.position == "TE").astype(float)
    p["def_recyds_pos"] = np.select([p.position == "WR", p.position == "TE", p.position == "RB"],
                                    [p.get("def_recyds_WR"), p.get("def_recyds_TE"), p.get("def_recyds_RB")], np.nan)
    return p


def rol(df, cual):
    ok = df.n_prev >= 2
    if cual == "qb":
        return ok & (df.position == "QB") & (df.ew_attempts >= 15)
    if cual == "rb":
        return ok & (df.position == "RB") & (df.ew_carries >= 5)
    if cual == "rec":
        return ok & df.position.isin(["WR", "TE", "RB"]) & (df.ew_targets >= 3)
    if cual == "td":
        return ok & df.position.isin(["WR", "TE", "RB"]) & ((df.ew_targets + df.ew_carries) >= 3)
    raise ValueError(cual)


def columnas_x(df):
    base = [c for c in df.columns if c.startswith(("ew_", "l3_", "ms_", "eq_", "def_"))]
    extra = ["n_prev", "n_temp", "dias_desc", "implicito", "spread_eq", "total_line", "domo", "viento", "local",
             "pos_qb", "pos_rb", "pos_wr", "pos_te", "def_recyds_pos"]
    return list(dict.fromkeys(base + extra))


def mitad(x):
    return math.floor(x) + 0.5


# ---------------------------------------------------------------- modelo
class ModeloMercado:
    def __init__(self, mercado):
        self.m = mercado
        self.y, self.tipo, self.rol, self.nombre = MERCADOS[mercado]

    def _nuevo(self):
        if self.tipo == "bin":
            return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_leaf_nodes=15,
                                                  min_samples_leaf=80, l2_regularization=1.0, random_state=7)
        loss = "squared_error" if self.tipo == "yds" else "poisson"
        return HistGradientBoostingRegressor(loss=loss, max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                             min_samples_leaf=80, l2_regularization=1.0, random_state=7)

    def _pred(self, est, X):
        if self.tipo == "bin":
            return est.predict_proba(X)[:, 1]
        return np.clip(est.predict(X), 0.05, None)

    def ajustar(self, tr):
        tr = tr[rol(tr, self.rol)]
        self.xcols = [c for c in columnas_x(tr) if tr[c].notna().any() and tr[c].nunique() > 1]
        yv = tr[self.y].values
        self.est = self._nuevo().fit(tr[self.xcols], yv)
        if self.tipo in ("yds", "cnt"):
            # residuos fuera de muestra por temporada -> distribucion escalada por quintil de proyeccion
            oof = np.full(len(tr), np.nan)
            temps = sorted(tr.season.unique())
            for s in temps[-4:]:
                a = tr.season != s
                e = self._nuevo().fit(tr.loc[a, self.xcols], yv[a.values])
                oof[(~a).values] = self._pred(e, tr.loc[~a, self.xcols])
            k = ~np.isnan(oof)
            pr, yy = oof[k], yv[k]
            self.cortes = np.quantile(pr, [0.2, 0.4, 0.6, 0.8])
            b = np.digitize(pr, self.cortes)
            self.razones = {i: (yy[b == i] / pr[b == i]) for i in range(5)}
        return self

    def media(self, df):
        return self._pred(self.est, df[self.xcols])

    def p_over(self, mu, linea):
        mu = np.asarray(mu, float)
        linea = np.broadcast_to(np.asarray(linea, float), mu.shape)
        if self.tipo == "bin":
            return mu  # P(TD >= 1)
        if self.tipo == "pois":
            return 1 - st.poisson.cdf(np.floor(linea), mu)
        b = np.digitize(mu, self.cortes)
        return np.array([np.mean(self.razones[bi] * m > l) for bi, m, l in zip(b, mu, linea)])

    def cuantiles(self, mu, qs=(0.25, 0.5, 0.75)):
        if self.tipo == "pois":
            return [float(st.poisson.ppf(q, mu)) for q in qs]
        if self.tipo == "bin":
            return [None] * len(qs)
        b = int(np.digitize([mu], self.cortes)[0])
        return [float(np.quantile(self.razones[b] * mu, q)) for q in qs]


class ModeloTotalEquipo:
    cols = ["implicito", "eq_pts", "def_pts", "spread_eq", "total_line", "local", "domo"]

    def ajustar(self, t):
        t = t.dropna(subset=["pts"] + self.cols)
        self.est = Ridge(alpha=5.0).fit(t[self.cols], t.pts)
        res = t.pts - self.est.predict(t[self.cols])
        self.sd = float(res.std())
        return self

    def media(self, t):
        return self.est.predict(t[self.cols])

    def p_over(self, mu, linea):
        return 1 - st.norm.cdf(np.floor(np.asarray(linea)) + 0.5, np.asarray(mu), self.sd)


# ---------------------------------------------------------------- validacion
def _z_brier(bm, bb):
    d = bb - bm
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 else 0.0


def validar(p, t, temporadas=(2022, 2023, 2024, 2025)):
    res = {}
    for m, (ycol, tipo, rl, nombre) in MERCADOS.items():
        filas = []
        for s in temporadas:
            tr = p[(p.season < s) & (p.season >= 2017)]
            te = p[(p.season == s) & rol(p, rl)]
            mod = ModeloMercado(m).ajustar(tr)
            mu = mod.media(te)
            y = te[ycol].values
            if tipo == "bin":
                linea = np.full(len(te), 0.5)
                base_p = float(tr.loc[rol(tr, rl), ycol].mean())
                ew_base = te["ew_td_total"].clip(0, None).values  # base del jugador
            else:
                ewc = "ew_" + ycol
                linea = te[ewc].apply(mitad).values
                trr = tr[rol(tr, rl)]
                base_p = float((trr[ycol] > trr[ewc].apply(mitad)).mean())
                ew_base = te[ewc].values
            po = mod.p_over(mu, linea)
            filas.append(pd.DataFrame({"season": s, "fecha": te.fecha.values, "y": y, "mu": mu, "ew": ew_base,
                                       "linea": linea, "p": po, "p_base": base_p}))
        f = pd.concat(filas, ignore_index=True).sort_values("fecha")
        over = (f.y > f.linea).astype(float) if tipo != "bin" else f.y
        bm, bb = (f.p - over) ** 2, (f.p_base - over) ** 2
        n = len(f)
        h = n // 2
        z = _z_brier(bm.values, bb.values)
        z1, z2 = _z_brier(bm.values[:h], bb.values[:h]), _z_brier(bm.values[h:], bb.values[h:])
        cal = float(f.p.mean() - over.mean())
        # calibracion por rango de p
        f["over"] = over.values
        f["rango"] = pd.cut(f.p, [0, .3, .4, .45, .5, .55, .6, .7, 1])
        tabla = f.groupby("rango", observed=True).agg(n=("p", "size"), p_media=("p", "mean"), real=("over", "mean"))
        r = {"nombre": nombre, "n": n, "brier_modelo": float(bm.mean()), "brier_base": float(bb.mean()),
             "skill": float(1 - bm.mean() / bb.mean()), "z": z, "z_mitades": [z1, z2],
             "p_media": float(f.p.mean()), "tasa_real": float(over.mean()), "calibracion": cal,
             "calibracion_por_rango": [{"rango": str(i), "n": int(rw.n), "p_media": round(float(rw.p_media), 3),
                                        "real": round(float(rw.real), 3)} for i, rw in tabla.iterrows()]}
        if tipo != "bin":
            r["mae_modelo"] = float(np.mean(np.abs(f.y - f.mu)))
            r["mae_ewma"] = float(np.mean(np.abs(f.y - f.ew)))
        ok = n >= 300 and r["skill"] > 0 and z >= 2.0 and z1 > 0 and z2 > 0 and abs(cal) <= 0.04
        r["estado"] = "publicable" if ok else "sin_validar"
        res[m] = r
        print(f"{m:13s} n={n:6d} skill={r['skill']:+.4f} z={z:5.2f} mitades=({z1:.2f},{z2:.2f}) "
              f"cal={cal:+.3f} {r.get('mae_modelo', 0):.1f}/{r.get('mae_ewma', 0):.1f} -> {r['estado']}", flush=True)
    # total de equipo contra la linea del mercado (puntos implicitos)
    filas = []
    for s in temporadas:
        tr = t[(t.season < s) & (t.season >= 2017)]
        te = t[(t.season == s)].dropna(subset=["pts"] + ModeloTotalEquipo.cols)
        mod = ModeloTotalEquipo().ajustar(tr)
        mu = mod.media(te)
        linea = te.implicito.apply(mitad).values
        trd = tr.dropna(subset=["pts"])
        base_p = float((trd.pts > trd.implicito.apply(mitad)).mean())
        filas.append(pd.DataFrame({"fecha": te.fecha.values, "y": te.pts.values, "mu": mu, "imp": te.implicito.values,
                                   "linea": linea, "p": mod.p_over(mu, linea), "p_base": base_p}))
    f = pd.concat(filas).sort_values("fecha")
    over = (f.y > f.linea).astype(float)
    bm, bb = (f.p - over) ** 2, (f.p_base - over) ** 2
    h = len(f) // 2
    z, z1, z2 = _z_brier(bm.values, bb.values), _z_brier(bm.values[:h], bb.values[:h]), _z_brier(bm.values[h:], bb.values[h:])
    cal = float(f.p.mean() - over.mean())
    ok = len(f) >= 300 and z >= 2 and z1 > 0 and z2 > 0 and abs(cal) <= 0.04
    res["total_equipo"] = {"nombre": "Total de puntos del equipo", "n": len(f), "brier_modelo": float(bm.mean()),
                           "brier_base": float(bb.mean()), "skill": float(1 - bm.mean() / bb.mean()), "z": z,
                           "z_mitades": [z1, z2], "p_media": float(f.p.mean()), "tasa_real": float(over.mean()),
                           "calibracion": cal, "mae_modelo": float(np.mean(np.abs(f.y - f.mu))),
                           "mae_implicito": float(np.mean(np.abs(f.y - f.imp))),
                           "estado": "publicable" if ok else "sin_validar"}
    print(f"total_equipo  n={len(f)} skill={res['total_equipo']['skill']:+.4f} z={z:.2f} ({z1:.2f},{z2:.2f}) cal={cal:+.3f} "
          f"mae {res['total_equipo']['mae_modelo']:.2f} vs implicito {res['total_equipo']['mae_implicito']:.2f} -> "
          f"{res['total_equipo']['estado']}", flush=True)
    return res


# ---------------------------------------------------------------- prediccion de un partido
def filas_partido(p, g, game_id, fuera=(), viento_kmh=None):
    """Agrega una fila vacia por jugador del partido (los que jugaron en la temporada) para sacar features as-of."""
    r = g[g.game_id == game_id].iloc[0]
    temp = int(r.season)
    nuevas = []
    for eq, rv in ((r.home_team, r.away_team), (r.away_team, r.home_team)):
        ult = p[(p.team == eq) & (p.season == temp)].sort_values("fecha").drop_duplicates("player_id", keep="last")
        for _, j in ult.iterrows():
            if j.player_display_name in fuera:
                continue
            fila = {c: np.nan for c in STATS}
            fila.update({"player_id": j.player_id, "player_display_name": j.player_display_name, "position": j.position,
                         "season": temp, "season_type": "REG", "game_id": game_id, "team": eq, "opponent_team": rv,
                         "fecha": pd.to_datetime(r.gameday), "home_team": r.home_team, "away_team": r.away_team,
                         "spread_line": r.spread_line, "total_line": r.total_line, "roof": r.roof,
                         "wind": (viento_kmh / 1.609) if viento_kmh is not None else r.wind,
                         "local": 1.0 if eq == r.home_team else 0.0, "_pred": 1})
            nuevas.append(fila)
    return pd.DataFrame(nuevas), r


def _dec(am):
    am = float(am)
    return 1 + am / 100 if am > 0 else 1 + 100 / abs(am)


def _precio(p_over, info, w_modelo=0.35):
    """EV contra la cuota de la casa. p_mercado sin vig si hay los dos lados; si solo hay uno se supone el otro igual.
    p_final = mezcla en logit con peso del modelo w (mercado de props sin CLV medido)."""
    o, u = info.get("over"), info.get("under")
    if o is None and u is None:
        return {"casa": info.get("casa")}
    o = o if o is not None else u
    u = u if u is not None else o
    io, iu = 1 / _dec(o), 1 / _dec(u)
    pm = io / (io + iu)
    lg = lambda x: math.log(x / (1 - x))
    pf = 1 / (1 + math.exp(-(lg(pm) + w_modelo * (lg(min(max(p_over, .01), .99)) - lg(pm)))))
    lados = {"over": (pf, _dec(o)), "under": (1 - pf, _dec(u))}
    lado = max(lados, key=lambda k: lados[k][0] * lados[k][1])
    return {"casa": info.get("casa"), "cuota_over": o, "cuota_under": u, "p_mercado_over": round(pm, 3),
            "p_final_over": round(pf, 3), "peso_modelo": w_modelo, "lado_valor": lado,
            "ev": round(lados[lado][0] * lados[lado][1] - 1, 4),
            "ev_modelo_puro": round(max(p_over * _dec(o), (1 - p_over) * _dec(u)) - 1, 4)}


lineas_info = {}


def predecir(p_raw, g_raw, game_id, fuera=(), viento_kmh=None, lineas=None):
    p, g = preparar(p_raw, g_raw)
    nuevas, r = filas_partido(p, g, game_id, fuera, viento_kmh)
    if viento_kmh is not None:
        g.loc[g.game_id == game_id, "wind"] = viento_kmh / 1.609
    p["_pred"] = 0
    todo = pd.concat([p, nuevas], ignore_index=True)
    t = tabla_equipos(g, todo[todo._pred == 0])
    todo = features_jugador(todo, t)
    hist, obj = todo[todo._pred == 0], todo[todo._pred == 1]
    # ultimo juego de cada jugador en la temporada (para saber si es titular hoy)
    salida = {"partido": game_id, "fecha": str(r.gameday), "local": r.home_team, "visita": r.away_team,
              "spread_line": float(r.spread_line), "total_line": float(r.total_line),
              "generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "jugadores": [], "equipos": []}
    for m, (ycol, tipo, rl, nombre) in MERCADOS.items():
        mod = ModeloMercado(m).ajustar(hist[hist.season >= 2017])
        o = obj[rol(obj, rl)]
        if not len(o):
            continue
        mu = mod.media(o)
        for (_, j), mm in zip(o.iterrows(), mu):
            ewc = "ew_" + (ycol if tipo != "bin" else "td_total")
            q = mod.cuantiles(mm)
            ln = None
            if lineas:
                ln = lineas.get((j.player_display_name, m))
            e = {"jugador": j.player_display_name, "equipo": j.team, "pos": j.position, "mercado": m, "nombre": nombre,
                 "proyeccion": round(float(mm), 2), "p25": q[0], "p50": q[1], "p75": q[2],
                 "promedio_ewma": round(float(j[ewc]), 2) if pd.notna(j[ewc]) else None,
                 "promedio_temporada": round(float(j["ms_" + (ycol if tipo != "bin" else "td_total")]), 2)
                 if pd.notna(j["ms_" + (ycol if tipo != "bin" else "td_total")]) else None,
                 "juegos_temporada": int(j.n_temp)}
            if tipo == "bin":
                e["p_td"] = round(float(mm), 3)
            else:
                lin = ln if ln is not None else (mitad(j[ewc]) if pd.notna(j[ewc]) else None)
                if lin is not None:
                    e["linea"] = lin
                    e["linea_fuente"] = "casa" if ln is not None else "promedio EWMA redondeado"
                    e["p_over"] = round(float(mod.p_over([mm], [lin])[0]), 3)
                    if ln is not None and lineas_info.get((j.player_display_name, m)):
                        e.update(_precio(e["p_over"], lineas_info[(j.player_display_name, m)]))
            salida["jugadores"].append(e)
    # total de equipo
    te = ModeloTotalEquipo().ajustar(t[(t.season >= 2017) & t.pts.notna()])
    tg = t[t.game_id == game_id]
    for _, rw in tg.iterrows():
        mu = float(te.media(rw.to_frame().T.astype({c: float for c in ModeloTotalEquipo.cols}))[0])
        lin = mitad(rw.implicito)
        salida["equipos"].append({"equipo": rw.team, "implicito_mercado": round(float(rw.implicito), 2),
                                  "proyeccion": round(mu, 2), "linea": lin, "p_over": round(float(te.p_over(mu, lin)), 3),
                                  "sd": round(te.sd, 2)})
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--partido")
    ap.add_argument("--fuera", default="")
    ap.add_argument("--viento_kmh", type=float)
    ap.add_argument("--sin_refrescar", action="store_true")
    ap.add_argument("--lineas", help="json: [{jugador, mercado, linea, over, under, casa}] con lineas reales de casas")
    a = ap.parse_args()
    p_raw, g_raw = cargar(refrescar_actual=not a.sin_refrescar)
    os.makedirs(os.path.join(REPO, "salida"), exist_ok=True)
    if a.validar:
        p, g = preparar(p_raw, g_raw)
        t = tabla_equipos(g, p)
        pf = features_jugador(p, t)
        res = validar(pf, t)
        res = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "criterio": "walk-forward 2022-2025; linea = EWMA del jugador redondeado a .5 (proxy, no linea de casa); "
                           "base = tasa historica de Over contra esa linea; total de equipo contra implicito del mercado",
               "mercados": res}
        with open(os.path.join(REPO, "salida", "validacion_props_nfl.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1, default=float)
    if a.partido:
        fuera = [x.strip() for x in a.fuera.split(",") if x.strip()]
        lineas = None
        if a.lineas:
            for x in json.load(open(a.lineas, encoding="utf-8")):
                lineas_info[(x["jugador"], x["mercado"])] = x
            lineas = {k: v["linea"] for k, v in lineas_info.items()}
        s = predecir(p_raw, g_raw, a.partido, fuera, a.viento_kmh, lineas)
        with open(os.path.join(REPO, "salida", "props_nfl.json"), "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=1, default=float)
        print(json.dumps(s, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
