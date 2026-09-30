# -*- coding: utf-8 -*-
"""
PASO 3 - nucleo/features.py

Capa de VARIABLES (features) compartida. A partir del box score por equipo-juego
(datos/beisbol.csv) construye, para cada juego, las variables predictivas de
local y visitante y sus DIFERENCIAS, calculadas AS-OF (cada juego solo ve lo
anterior a su fecha -> cero fuga de informacion).

Sirve igual para MLB, KBO, LMP, LVBP, LIDOM, ABL, NPB: todas comparten esquema.
Cada estadistica se encoge hacia la media de su liga-temporada (Marcel), asi los
equipos con pocos juegos no se disparan.

Variables por equipo (as-of, ritmo por juego / por 9 IP):
  ofensiva:  cs (carreras anotadas/juego), obp, iso, k_pct, bb_pct
  pitcheo:   ca (carreras permitidas/juego), fip, k9, bb9, hr9, whip
  ritmo:     elo (con ventaja local y regresion por temporada)
  contexto:  descanso (dias desde el ultimo juego)

Salida de construir(): lista de dicts, uno por juego, con:
  meta:   gamePk, league, season, game_date, home, away
  target: y_home (1 si gano local), total (carreras totales)
  feats:  <stat>_dif = local - visita, para cada estadistica de arriba,
          mas elo_home / elo_away por si un modelo los quiere directos.

Solo stdlib. Colocar en:  C:\\Edgeline\\nucleo\\features.py

Prueba (en C:\\Edgeline, ya con datos/beisbol.csv):
    python -c "import sys; sys.path.insert(0,'.'); from nucleo import features; features.diagnostico('beisbol')"
"""
import math, datetime as _dt

try:
    from nucleo import io
except ImportError:
    import io  # cuando se corre desde dentro de nucleo/

# ------------------------------------------------------------------ ELO
ELO_BASE   = 1500.0
ELO_K      = 6.0
ELO_HFA    = 24.0     # ventaja local en puntos ELO
ELO_REGR   = 0.70     # cuanto se conserva al cambiar de temporada (regresa 30%)

# parametros ELO EN USO (los cambia el afinador por liga; default = los de arriba)
_HFA, _K, _REGR = ELO_HFA, ELO_K, ELO_REGR

def set_elo(hfa=None, k=None, regr=None):
    """Fija los parametros ELO en uso (para el afinador o para produccion por liga)."""
    global _HFA, _K, _REGR
    if hfa is not None:  _HFA = hfa
    if k is not None:    _K = k
    if regr is not None: _REGR = regr

def _params_guardados(deporte, liga):
    """Lee nucleo/_calib/elo_<deporte>_<liga>.json si existe -> (hfa,k,regr) o None."""
    import os, json
    try:
        ruta = os.path.join(io.BASE, "nucleo", "_calib", "elo_%s_%s.json" % (deporte, io.norm(liga)))
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("hfa", ELO_HFA), d.get("k", ELO_K), d.get("regr", ELO_REGR)
    except Exception:
        return None

def _elo_esp(dif):
    return 1.0 / (1.0 + 10.0 ** (-dif / 400.0))

# ------------------------------------------------------------------ util
def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None

def _ip(x):
    """innings pitched estilo baseball: 6.2 = 6 innings + 2 outs = 6.667."""
    v = _f(x)
    if v is None:
        return None
    ent = int(v)
    dec = round(v - ent, 1)
    outs = int(round(dec * 10))
    return ent + (outs / 3.0 if outs in (1, 2) else 0.0)

def _fecha(s):
    s = str(s or "")[:10]
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None

# ------------------------------------------------------------------ acumulador por equipo
class _Acum:
    """Suma corrida de un equipo, as-of. Se consulta ANTES de sumar el juego."""
    __slots__ = ("j", "cs", "ca", "ab", "h", "bb", "so", "hr", "b2", "b3",
                 "sf", "hbp", "ip", "er", "bb_p", "so_p", "hr_p", "h_p", "elo", "ult_fecha")
    def __init__(self):
        self.j = 0
        self.cs = self.ca = 0.0
        self.ab = self.h = self.bb = self.so = self.hr = self.b2 = self.b3 = 0.0
        self.sf = self.hbp = 0.0
        self.ip = self.er = self.bb_p = self.so_p = self.hr_p = self.h_p = 0.0
        self.elo = ELO_BASE
        self.ult_fecha = None

    def tasas(self):
        """Devuelve las tasas actuales (o None si aun no hay juegos)."""
        if self.j == 0:
            return None
        pa = self.ab + self.bb + self.hbp + self.sf
        singles = self.h - self.b2 - self.b3 - self.hr
        tb = singles + 2 * self.b2 + 3 * self.b3 + 4 * self.hr
        obp = (self.h + self.bb + self.hbp) / pa if pa else None
        iso = (tb - self.h) / self.ab if self.ab else None
        k_pct = self.so / pa if pa else None
        bb_pct = self.bb / pa if pa else None
        ip = self.ip or 0.0
        fip = ((13 * self.hr_p) + 3 * self.bb_p - 2 * self.so_p) / ip + 3.10 if ip else None
        k9 = 9 * self.so_p / ip if ip else None
        bb9 = 9 * self.bb_p / ip if ip else None
        hr9 = 9 * self.hr_p / ip if ip else None
        whip = (self.bb_p + self.h_p) / ip if ip else None
        return {
            "cs": self.cs / self.j, "ca": self.ca / self.j,
            "obp": obp, "iso": iso, "k_pct": k_pct, "bb_pct": bb_pct,
            "fip": fip, "k9": k9, "bb9": bb9, "hr9": hr9, "whip": whip,
        }

    def sumar(self, r, cs, ca):
        self.j += 1
        self.cs += cs; self.ca += ca
        self.ab   += _f(r.get("bat_atBats")) or 0
        self.h    += _f(r.get("bat_hits")) or 0
        self.bb   += _f(r.get("bat_baseOnBalls")) or 0
        self.so   += _f(r.get("bat_strikeOuts")) or 0
        self.hr   += _f(r.get("bat_homeRuns")) or 0
        self.b2   += _f(r.get("bat_doubles")) or 0
        self.b3   += _f(r.get("bat_triples")) or 0
        self.sf   += _f(r.get("bat_sacFlies")) or 0
        self.hbp  += _f(r.get("bat_hitByPitch")) or 0
        self.ip   += _ip(r.get("pit_inningsPitched")) or 0
        self.er   += _f(r.get("pit_earnedRuns")) or 0
        self.bb_p += _f(r.get("pit_baseOnBalls")) or 0
        self.so_p += _f(r.get("pit_strikeOuts")) or 0
        self.hr_p += _f(r.get("pit_homeRuns")) or 0
        self.h_p  += _f(r.get("pit_hits")) or 0

# ------------------------------------------------------------------ armado as-of
STATS = ["cs", "ca", "obp", "iso", "k_pct", "bb_pct", "fip", "k9", "bb9", "hr9", "whip"]

def _emparejar(filas):
    """El CSV trae 2 filas por juego (una por equipo). Las une en (home, away)."""
    porjuego = {}
    for r in filas:
        gp = str(r.get("gamePk") or r.get("game_id") or "")
        porjuego.setdefault(gp, []).append(r)
    juegos = []
    for gp, par in porjuego.items():
        if len(par) != 2:
            continue
        h = next((x for x in par if str(x.get("is_home")) in ("1", "1.0", "True")), None)
        a = next((x for x in par if x is not h), None)
        if h is None or a is None:
            continue
        f = _fecha(h.get("game_date"))
        if not f:
            continue
        juegos.append((f, gp, h, a))
    juegos.sort(key=lambda t: (t[0], t[1]))
    return juegos

def construir(deporte="beisbol", liga=None, min_juegos=5, elo=None):
    """
    Devuelve (features, saltados). features es lista de dicts as-of.
    min_juegos: no emite el juego hasta que AMBOS equipos tengan >= min_juegos.
    elo: (hfa, k, regr) para forzar parametros ELO (lo usa el afinador). Si es None
         y se pide UNA liga, carga los afinados de esa liga si existen.
    """
    if elo is not None:
        set_elo(*elo)
    elif liga is not None:
        g = _params_guardados(deporte, liga)
        if g:
            set_elo(*g)
        else:
            set_elo(ELO_HFA, ELO_K, ELO_REGR)
    else:
        set_elo(ELO_HFA, ELO_K, ELO_REGR)
    filas = io.cargar_juegos(deporte, liga)
    juegos = _emparejar(filas)
    # media de liga-temporada para encoger (Marcel), calculada en una pasada previa
    lg_stats = _medias_liga_temporada(juegos)
    acum = {}          # (liga, season, team) -> _Acum
    out, saltados = [], 0

    for f, gp, h, a in juegos:
        lg = io.norm(h.get("league") or h.get("liga"))
        season = str(h.get("season") or f.year)
        th = _clave(acum, lg, season, h.get("team"))
        ta = _clave(acum, lg, season, a.get("team"))
        csh, cah = _f(h.get("runs")), _f(h.get("runs_opp"))
        csa, caa = _f(a.get("runs")), _f(a.get("runs_opp"))
        if None in (csh, csa):
            saltados += 1; continue

        pre_h, pre_a = th.tasas(), ta.tasas()
        listo = th.j >= min_juegos and ta.j >= min_juegos and pre_h and pre_a
        if listo:
            med = lg_stats.get((lg, season)) or {}
            fila = {"gamePk": gp, "league": lg, "season": season,
                    "game_date": f.isoformat(),
                    "home": h.get("team"), "away": a.get("team"),
                    "y_home": 1 if csh > csa else 0,
                    "total": (csh or 0) + (csa or 0),
                    "marg_home": (csh or 0) - (csa or 0),
                    "cubierto_rl": 1 if ((csh or 0) - (csa or 0)) >= 2 else 0,
                    "elo_home": round(th.elo, 1), "elo_away": round(ta.elo, 1),
                    "elo_dif": round(th.elo + _HFA - ta.elo, 1),
                    "descanso_dif": _descanso(th, f) - _descanso(ta, f)}
            for s in STATS:
                vh = _encoge(pre_h.get(s), med.get(s), th.j)
                va = _encoge(pre_a.get(s), med.get(s), ta.j)
                fila[s + "_dif"] = (round(vh - va, 4) if (vh is not None and va is not None) else None)
            # NIVELES para TOTALES (no diferencias): carreras anotadas/permitidas as-of
            # de cada equipo, mas el ritmo de carreras de la liga. Con esto se estima
            # el total esperado (Log5 de carreras), que las diferencias no permiten.
            fila["of_home"] = round(_encoge(pre_h.get("cs"), med.get("cs"), th.j), 3)
            fila["of_away"] = round(_encoge(pre_a.get("cs"), med.get("cs"), ta.j), 3)
            fila["df_home"] = round(_encoge(pre_h.get("ca"), med.get("ca"), th.j), 3)
            fila["df_away"] = round(_encoge(pre_a.get("ca"), med.get("ca"), ta.j), 3)
            fila["lg_rs"] = round(med.get("cs") or 4.5, 3)
            out.append(fila)

        # actualizar ELO (MOV simple) y acumular DESPUES de emitir
        _actualiza_elo(th, ta, csh, csa)
        th.ult_fecha = f; ta.ult_fecha = f
        th.sumar(h, csh, cah if cah is not None else csa)
        ta.sumar(a, csa, caa if caa is not None else csh)

    return out, saltados

def _clave(acum, lg, season, team):
    k = (lg, season, io.norm(team))
    if k not in acum:
        ac = _Acum()
        # arrastre de ELO de la temporada anterior del mismo equipo (regresion)
        prev = _elo_previo(acum, lg, season, io.norm(team))
        if prev is not None:
            ac.elo = ELO_BASE + (prev - ELO_BASE) * _REGR
        acum[k] = ac
    return acum[k]

def _elo_previo(acum, lg, season, team_norm):
    try:
        sprev = str(int(season) - 1)
    except ValueError:
        return None
    ac = acum.get((lg, sprev, team_norm))
    return ac.elo if ac else None

def _actualiza_elo(th, ta, csh, csa):
    esp_h = _elo_esp(th.elo + _HFA - ta.elo)
    res_h = 1.0 if csh > csa else (0.0 if csh < csa else 0.5)
    mov = math.log(abs(csh - csa) + 1) if csh != csa else 1.0
    delta = _K * mov * (res_h - esp_h)
    th.elo += delta; ta.elo -= delta

def _descanso(ac, f):
    if ac.ult_fecha is None:
        return 3  # neutro para el primer juego
    return min((f - ac.ult_fecha).days, 7)

def _encoge(val, media, n, k=6.0):
    """Marcel: mezcla el valor del equipo con la media de liga segun tamano de muestra."""
    if val is None:
        return media
    if media is None:
        return val
    return (n * val + k * media) / (n + k)

def _medias_liga_temporada(juegos):
    """Media simple de cada stat por (liga, season) para encoger. Una pasada aparte,
    usando el total de temporada (para el encogimiento no importa la fuga)."""
    tmp, out = {}, {}
    for f, gp, h, a in juegos:
        lg = io.norm(h.get("league") or h.get("liga"))
        season = str(h.get("season") or f.year)
        ac = tmp.setdefault((lg, season), _Acum())
        csh, cah = _f(h.get("runs")), _f(h.get("runs_opp"))
        csa, caa = _f(a.get("runs")), _f(a.get("runs_opp"))
        if None in (csh, csa):
            continue
        ac.sumar(h, csh, cah if cah is not None else csa)
        ac.sumar(a, csa, caa if caa is not None else csh)
    for k, ac in tmp.items():
        out[k] = ac.tasas() or {}
    return out

# ------------------------------------------------------------------ diagnostico
def diagnostico(deporte="beisbol", liga=None):
    feats, saltados = construir(deporte, liga)
    print("Deporte: %s  liga: %s" % (deporte, liga or "todas"))
    print("Juegos con features: %d   (saltados por datos/muestra: %d)" % (len(feats), saltados))
    if not feats:
        print("Sin features. Falta datos/%s.csv o columnas bat_/pit_." % deporte); return
    ligas = {}
    for r in feats:
        ligas[r["league"]] = ligas.get(r["league"], 0) + 1
    print("Por liga:", ", ".join("%s=%d" % (k, v) for k, v in sorted(ligas.items())))
    ej = feats[-1]
    print("\nEjemplo (ultimo juego):")
    for k in ("game_date", "league", "home", "away", "y_home", "total",
              "elo_dif", "cs_dif", "ca_dif", "obp_dif", "fip_dif", "k9_dif", "descanso_dif"):
        print("  %-14s %s" % (k, ej.get(k)))
    cobertura = {}
    for s in STATS:
        c = sum(1 for r in feats if r.get(s + "_dif") is not None)
        cobertura[s] = round(100 * c / len(feats))
    print("\n%% de juegos con cada variable (100 = box score completo):")
    print("  " + ", ".join("%s=%d%%" % (s, cobertura[s]) for s in STATS))


if __name__ == "__main__":
    import sys
    diagnostico(sys.argv[1] if len(sys.argv) > 1 else "beisbol",
                sys.argv[2] if len(sys.argv) > 2 else None)
