# -*- coding: utf-8 -*-
"""
KBO AHORA v2 - prediccion rapida de KBO sin correr todo el pipeline.

Usa tus datos historicos REALES (data_maestra/baseball_game_results_2022_2026.csv)
para un ELO de beisbol + tasas de carreras por equipo, y AHORA tambien:
  - AJUSTE POR PITCHER ABRIDOR (lee 11_players/baseball/pitchers_kbo.csv): un
    abridor mejor que el promedio baja las carreras del rival y sube la probabilidad.
  - CONFIANZA (Alta/Media/Baja + estrellas): combina el margen del modelo, el tamano
    de muestra, si ELO y carreras coinciden en el favorito, y si hubo datos de pitcher.
  - EDGE VS MERCADO (opcional): si pegas las cuotas, marca donde hay valor real.

Formato de los partidos:  VISITANTE [pitcher] @ LOCAL [pitcher]  ; cuotas opcionales
    "Doosan [Benjamin] @ NC Dinos [Lee Jae-Hak]"
    "SSG [Avila] @ LG Twins [Tolhurst] #ml 2.05 1.80 #ou 9.5 1.90 1.90"
      #ml  <cuota_visitante> <cuota_local>       (decimal)
      #ou  <linea> <cuota_over> <cuota_under>     (decimal)

Uso (en C:\\Edgeline):
    python kbo_ahora.py --juegos "Doosan [Benjamin] @ NC Dinos [Lee Jae-Hak], KIA [Oller] @ KT Wiz [Allen]"
    python kbo_ahora.py                      # lee kbo_manana.txt (un partido por linea)

Salidas: kbo_ahora.csv y kbo_ahora.html (se abre solo).
"""
import argparse, csv, io, json, math, os, re, unicodedata, datetime as dt

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline")
RES = os.path.join(BASE, "data_maestra", "baseball_game_results_2022_2026.csv")
PITCHERS = os.path.join(BASE, "11_players", "baseball", "pitchers_kbo.csv")
CALIB = "kbo_calib.json"   # lo genera kbo_calibrar.py; si existe, recalibra las probabilidades

BASE_ELO = 1500.0
K = 6.0
HFA = 24.0
REGRESION = 0.70
# --- constantes de la metodologia sabermetrica ---
K_TEAM = 30.0          # regresion de las tasas de equipo a la media (en juegos)
IP_REG_FIP = 60.0      # regresion Marcel del FIP a la media de liga (en innings)
INN_ABRIDOR = 5.3      # innings tipicos de un abridor KBO (de 9); el resto = bullpen
UNEARNED = 1.08        # RA total ~ 8% mas que ER (para comparar FIP con carreras del equipo)
VENTAJA_LOCAL = 0.03   # empuje de local sobre las carreras esperadas (~54% win de local)
PYTHAG_K = 0.287       # exponente Pythagenpat: x = RPG^0.287 (Smyth/Patriot)
NB_DISP = 4.0          # dispersion de la negativa binomial de carreras por equipo

KBO = {
    "doosan": "Doosan Bears", "lotte": "Lotte Giants", "samsung": "Samsung Lions",
    "hanwha": "Hanwha Eagles", "kia": "KIA Tigers", "lg": "LG Twins", "nc": "NC Dinos",
    "kt": "KT Wiz", "ktwiz": "KT Wiz", "ktwizsuwon": "KT Wiz",
    "kiwoom": "Kiwoom Heroes", "ssg": "SSG Landers",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def num(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError):
        return None


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def cargar_calib():
    """coeficientes de recalibracion (Platt) si existen: logit(p_cal)=a+b*logit(p)."""
    for ruta in (os.path.join(BASE, CALIB), CALIB):
        if os.path.exists(ruta):
            try:
                d = json.load(io.open(ruta, encoding="utf-8"))
                return float(d["a"]), float(d["b"])
            except Exception:
                return None
    return None


_CALIB = cargar_calib()


def recalibrar(p):
    """aplica la calibracion Platt si esta disponible; si no, deja p igual."""
    if not _CALIB:
        return p
    a, b = _CALIB
    p = min(max(p, 1e-6), 1 - 1e-6)
    z = a + b * math.log(p / (1 - p))
    if z < -35:
        return 0.02
    if z > 35:
        return 0.98
    return 1.0 / (1.0 + math.exp(-z))


# ---------------------------------------------------------------- historial + ELO
def cargar_kbo():
    if not os.path.exists(RES):
        raise SystemExit("No encuentro %s" % RES)
    filas = []
    with io.open(RES, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            if norm(r.get("league")) != "kbo":
                continue
            hs, as_ = num(r.get("home_score")), num(r.get("away_score"))
            if hs is None or as_ is None:
                continue
            filas.append({"fecha": (r.get("game_date") or "")[:10],
                          "home": r.get("home_team", ""), "away": r.get("away_team", ""),
                          "hs": hs, "as": as_, "season": (r.get("game_date") or "")[:4]})
    filas.sort(key=lambda x: x["fecha"])
    return filas


def entrenar(filas):
    elo = {}; temp_prev = None
    temp_actual = max((f["season"] for f in filas), default=None)
    temps = {temp_actual, str(int(temp_actual) - 1)} if temp_actual and temp_actual.isdigit() else set()
    acum = {}; juegos_eq = {}; tot = []
    for f in filas:
        h, a = norm(f["home"]), norm(f["away"]); s = f["season"]
        if s != temp_prev and temp_prev is not None:
            for t in list(elo):
                elo[t] = BASE_ELO + REGRESION * (elo[t] - BASE_ELO)
        temp_prev = s
        elo.setdefault(h, BASE_ELO); elo.setdefault(a, BASE_ELO)
        ph = 1.0 / (1.0 + 10 ** (-((elo[h] + HFA) - elo[a]) / 400.0))
        res = 1.0 if f["hs"] > f["as"] else (0.5 if f["hs"] == f["as"] else 0.0)
        difg = f["hs"] - f["as"]
        mult = math.log(abs(difg) + 1.0) if difg != 0 else 1.0
        aj = K * mult * (res - ph)
        elo[h] += aj; elo[a] -= aj
        if s in temps:
            w = 1.0 if s == temp_actual else 0.5
            for eq, rs, ra in ((h, f["hs"], f["as"]), (a, f["as"], f["hs"])):
                d = acum.setdefault(eq, [0.0, 0.0, 0.0]); d[0] += rs * w; d[1] += ra * w; d[2] += w
        if s == temp_actual:
            juegos_eq[h] = juegos_eq.get(h, 0) + 1; juegos_eq[a] = juegos_eq.get(a, 0) + 1
            tot.append(f["hs"] + f["as"])
    media = (sum(tot) / len(tot)) if tot else 9.0
    rs = {t: acum[t][0] / acum[t][2] for t in acum if acum[t][2] > 0}
    ra = {t: acum[t][1] / acum[t][2] for t in acum if acum[t][2] > 0}
    canon = {}
    for f in filas:
        for raw in (f["home"], f["away"]):
            canon.setdefault(norm(raw), raw)
    return {"elo": elo, "rs": rs, "ra": ra, "media": media, "juegos_eq": juegos_eq, "canon": canon}


# ---------------------------------------------------------------- pitchers
def cargar_pitchers():
    """Devuelve (por_nombre_norm -> metrica, liga_avg). Metrica = FIP si hay, si no ERA."""
    if not os.path.exists(PITCHERS):
        return {}, None
    por = {}; vals = []
    with io.open(PITCHERS, encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            nom = r.get("nombre") or r.get("player") or ""
            met = num(r.get("fip"))
            if met is None:
                met = num(r.get("era"))
            ip = num(r.get("ip")) or 0
            if not nom or met is None:
                continue
            por[norm(nom)] = {"metrica": met, "nombre": nom, "ip": ip,
                              "era": num(r.get("era")), "fip": num(r.get("fip"))}
            if ip >= 20:                 # solo lanzadores con carga para el promedio
                vals.append(met)
    liga_avg = (sum(vals) / len(vals)) if vals else None
    return por, liga_avg


def _toks(nombre):
    """tokens normalizados de >=3 letras (ignora iniciales como W., A., C.J.)."""
    return set(t for t in (norm(p) for p in re.split(r"[\s\-]+", str(nombre or ""))) if len(t) >= 3)


def buscar_pitcher(nombre, por):
    """Empareja el abridor con el catalogo de forma ESTRICTA para no confundir
    pitchers parecidos (p.ej. 'Park Jun-Yeong' con 'Ko Yeong-pyo').
    Regla: coincidencia exacta, o
      - nombre de un solo token (extranjero, 'Oller'): ese token debe existir
        EXACTO en el catalogo y ser UNICO.
      - nombre de varios tokens (coreano, 'Park Jun-Yeong'): deben coincidir al
        menos 2 tokens y el mejor candidato debe ser unico.
    Si no esta seguro, devuelve None (mejor sin ajuste que con el pitcher equivocado)."""
    if not nombre:
        return None
    nq = norm(nombre)
    if nq in por:
        return por[nq]
    q = _toks(nombre)
    if not q:
        return None
    cands = []
    for key, v in por.items():
        nt = _toks(v.get("nombre"))
        comp = len(q & nt)
        if comp > 0:
            cands.append((comp, v, nt))
    if not cands:
        return None
    mejor = max(c[0] for c in cands)
    top = [c for c in cands if c[0] == mejor]
    if len(q) == 1:
        tok = next(iter(q))
        con_tok = [c for c in cands if tok in c[2]]
        return con_tok[0][1] if (len(con_tok) == 1 and mejor >= 1) else None
    # varios tokens: exige >=2 coincidencias y un unico mejor
    if mejor >= 2 and len(top) == 1:
        return top[0][1]
    return None


# ---------------------------------------------------------------- prediccion
def resolver_equipo(nombre, equipos):
    n = norm(nombre)
    for k, full in KBO.items():
        if n == k or n == norm(full):
            n = norm(full); break
    if n in equipos:
        return equipos[n]
    for key, canon in equipos.items():
        if n and (n in key or key in n):
            return canon
    return None


def _shrink(valor, n, media, k):
    """regresion a la media segun tamano de muestra (Marcel para tasas de equipo)."""
    return (n * valor + k * media) / (n + k) if (n + k) > 0 else media


def _sp_ra9(pit, lg_fip):
    """RA/9 proyectada del abridor: FIP regresado a la media de liga por sus innings
    (Marcel), convertido a carreras totales. Devuelve (ra9, hubo_dato)."""
    if not pit or lg_fip is None:
        return None, False
    fip = pit.get("metrica")
    if fip is None:
        fip = pit.get("fip") if pit.get("fip") is not None else pit.get("era")
    if fip is None:
        return None, False
    ip = pit.get("ip") or 0
    fip_proj = (ip * fip + IP_REG_FIP * lg_fip) / (ip + IP_REG_FIP)
    return fip_proj * UNEARNED, True


def predecir(vis, loc, M, pit_vis, pit_loc, lg_fip):
    nl, nv = norm(loc), norm(vis)
    lg_rs = M["media"] / 2.0                       # carreras de liga por equipo/juego
    nL = M["juegos_eq"].get(nl, 0); nV = M["juegos_eq"].get(nv, 0)
    # tasas de equipo regresadas a la media (Marcel)
    off_l = _shrink(M["rs"].get(nl, lg_rs), nL, lg_rs, K_TEAM)
    def_l = _shrink(M["ra"].get(nl, lg_rs), nL, lg_rs, K_TEAM)
    off_v = _shrink(M["rs"].get(nv, lg_rs), nV, lg_rs, K_TEAM)
    def_v = _shrink(M["ra"].get(nv, lg_rs), nV, lg_rs, K_TEAM)
    if nl not in M["rs"] and nv not in M["rs"]:
        return None

    # prevencion de carreras del juego = abridor (su fraccion de innings) + bullpen/equipo
    w_sp = INN_ABRIDOR / 9.0
    ra9_sp_l, ok_l = _sp_ra9(pit_loc, lg_fip)
    ra9_sp_v, ok_v = _sp_ra9(pit_vis, lg_fip)
    def_game_l = (w_sp * ra9_sp_l + (1 - w_sp) * def_l) if ok_l else def_l
    def_game_v = (w_sp * ra9_sp_v + (1 - w_sp) * def_v) if ok_v else def_v

    # carreras esperadas por el metodo multiplicativo (Log5 / odds ratio)
    car_l = off_l * def_game_v / lg_rs
    car_v = off_v * def_game_l / lg_rs
    # ventaja de local sobre las carreras
    car_l *= (1 + VENTAJA_LOCAL); car_v *= (1 - VENTAJA_LOCAL)
    car_l = max(1.0, car_l); car_v = max(1.0, car_v)
    total = car_l + car_v

    # probabilidad de ganar del local por Pythagenpat
    rpg = max(1.0, car_l + car_v)
    x = rpg ** PYTHAG_K
    p_home = (car_l ** x) / (car_l ** x + car_v ** x)
    p_home = recalibrar(p_home)              # recalibracion Platt si esta disponible
    p_home = clamp(p_home, 0.05, 0.95)

    # confianza
    n = min(nL, nV)
    gap = abs(p_home - 0.5) * 2
    muestra = min(1.0, n / 15.0)
    acuerdo = 1.0 if ((car_l > car_v) == (p_home >= 0.5)) else 0.0
    pit_ok = 1.0 if (ok_v and ok_l) else (0.5 if (ok_v or ok_l) else 0.0)
    conf = 100 * (0.45 * gap + 0.15 * muestra + 0.25 * acuerdo + 0.15 * pit_ok)
    nivel = "Alta" if conf >= 62 else ("Media" if conf >= 42 else "Baja")
    estrellas = int(clamp(round(conf / 20.0), 1, 5))

    return {"p_home": p_home, "car_l": car_l, "car_v": car_v, "total": total,
            "conf": conf, "nivel": nivel, "estrellas": estrellas,
            "pit_v": pit_vis, "pit_l": pit_loc, "ok_v": ok_v, "ok_l": ok_l}


# ---------------------------------------------------------------- negativa binomial (over/under)
def _nb_pmf(mu, r, kmax):
    """vector pmf de una negativa binomial con media mu y dispersion r."""
    p = r / (r + mu)
    out = []
    lp, l1p = math.log(p), math.log(1 - p)
    for k in range(kmax + 1):
        logpmf = (math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * lp + k * l1p)
        out.append(math.exp(logpmf))
    return out


def prob_over(mu_a, mu_b, linea, r=NB_DISP, kmax=25):
    """P(carreras_totales > linea) con dos negativas binomiales independientes."""
    pa = _nb_pmf(mu_a, r, kmax); pb = _nb_pmf(mu_b, r, kmax)
    total = [0.0] * (2 * kmax + 1)
    for i, va in enumerate(pa):
        if va < 1e-12:
            continue
        for j, vb in enumerate(pb):
            total[i + j] += va * vb
    corte = math.floor(linea) + 1           # 9.5 -> over si total >= 10
    return sum(total[corte:])


# ---------------------------------------------------------------- parseo de entrada
def parse_juego(txt):
    """Devuelve (vis, pit_vis, loc, pit_loc, cuotas). cuotas = dict opcional."""
    cuotas = {}
    m_ml = re.search(r"#ml\s+([\d.]+)\s+([\d.]+)", txt, re.I)
    if m_ml:
        cuotas["ml"] = (float(m_ml.group(1)), float(m_ml.group(2)))
    m_ou = re.search(r"#ou\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", txt, re.I)
    if m_ou:
        cuotas["ou"] = (float(m_ou.group(1)), float(m_ou.group(2)), float(m_ou.group(3)))
    txt = re.sub(r"#(ml|ou).*$", "", txt, flags=re.I).strip()
    if "@" not in txt:
        return None
    izq, der = txt.split("@", 1)
    def sep(x):
        mm = re.search(r"\[(.+?)\]", x)
        pit = mm.group(1).strip() if mm else None
        eq = re.sub(r"\[.+?\]", "", x).strip()
        return eq, pit
    vis, pit_v = sep(izq); loc, pit_l = sep(der)
    return vis, pit_v, loc, pit_l, cuotas


def edge_mercado(p, cuotas):
    out = {}
    if "ml" in cuotas:
        dv, dl = cuotas["ml"]
        iv, il = 1.0 / dv, 1.0 / dl
        nv_local = il / (il + iv)                 # prob sin vig del local
        pick_local = p["p_home"] >= 0.5
        p_mod = p["p_home"] if pick_local else 1 - p["p_home"]
        nv = nv_local if pick_local else 1 - nv_local
        out["ml_edge"] = round(100 * (p_mod - nv), 1)
        out["ml_cuota"] = dl if pick_local else dv
    if "ou" in cuotas:
        linea, do, du = cuotas["ou"]
        p_over = prob_over(p["car_l"], p["car_v"], linea)   # negativa binomial
        io_, iu = 1.0 / do, 1.0 / du
        nv_over = io_ / (io_ + iu)
        if p_over >= nv_over:
            out["ou_pick"] = "OVER"; out["ou_edge"] = round(100 * (p_over - nv_over), 1); out["ou_cuota"] = do
        else:
            out["ou_pick"] = "UNDER"; out["ou_edge"] = round(100 * ((1 - p_over) - (1 - nv_over)), 1); out["ou_cuota"] = du
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--juegos")
    ap.add_argument("--archivo", default="kbo_manana.txt")
    ap.add_argument("--no-abrir", action="store_true")
    args = ap.parse_args()

    filas = cargar_kbo()
    if not filas:
        raise SystemExit("No hay resultados de KBO en el historial.")
    M = entrenar(filas)
    equipos = {norm(v): v for v in M["canon"].values()}
    por_pit, liga_avg = cargar_pitchers()
    print("Historial KBO: %d juegos | equipos: %d | pitchers: %d (liga avg %s) | ult. fecha %s"
          % (len(filas), len(M["elo"]), len(por_pit),
             ("%.2f" % liga_avg) if liga_avg else "n/d", filas[-1]["fecha"]))

    crudos = []
    if args.juegos:
        crudos = [p for p in re.split(r",(?![^\[]*\])", args.juegos) if p.strip()]
    elif os.path.exists(args.archivo):
        crudos = [l for l in io.open(args.archivo, encoding="utf-8").read().splitlines() if l.strip()]
    if not crudos:
        print('\nDame los partidos, ej:')
        print('  python kbo_ahora.py --juegos "Doosan [Benjamin] @ NC Dinos [Lee Jae-Hak]"')
        print("\nEquipos:", ", ".join(sorted(set(M["canon"].values()))))
        return

    filas_out = []
    for c in crudos:
        pj = parse_juego(c)
        if not pj:
            print("  (ignoro '%s')" % c.strip()); continue
        vis_raw, pit_v_raw, loc_raw, pit_l_raw, cuotas = pj
        vis, loc = resolver_equipo(vis_raw, equipos), resolver_equipo(loc_raw, equipos)
        if not vis or not loc:
            print("  (no reconozco '%s' o '%s')" % (vis_raw, loc_raw)); continue
        pit_v = buscar_pitcher(pit_v_raw, por_pit) if pit_v_raw else None
        pit_l = buscar_pitcher(pit_l_raw, por_pit) if pit_l_raw else None
        if pit_v_raw and not pit_v:
            print("  ! abridor no encontrado: '%s' (%s) -> sin ajuste de pitcher" % (pit_v_raw, vis))
        if pit_l_raw and not pit_l:
            print("  ! abridor no encontrado: '%s' (%s) -> sin ajuste de pitcher" % (pit_l_raw, loc))
        p = predecir(vis, loc, M, pit_v, pit_l, liga_avg)
        if not p:
            continue
        gana = loc if p["p_home"] >= 0.5 else vis
        prob = round(100 * (p["p_home"] if p["p_home"] >= 0.5 else 1 - p["p_home"]), 1)
        row = {"visitante": vis, "local": loc, "gana": gana, "prob_%": prob,
               "confianza": p["nivel"], "estrellas": p["estrellas"],
               "carreras_visit": round(p["car_v"], 1), "carreras_local": round(p["car_l"], 1),
               "total_est": round(p["total"], 1),
               "abridor_visit": (pit_v["nombre"] if pit_v else (pit_v_raw or "-")),
               "abridor_local": (pit_l["nombre"] if pit_l else (pit_l_raw or "-"))}
        row.update(edge_mercado(p, cuotas))
        filas_out.append(row)

    if not filas_out:
        return
    filas_out.sort(key=lambda x: (-x["estrellas"], -x["prob_%"]))

    print("\n%-15s %-15s %-12s %5s %-6s %6s  %-14s" % (
        "VISITANTE", "LOCAL", "GANA", "PROB", "CONF", "TOTAL", "PICKS/EDGE"))
    print("-" * 82)
    for f in filas_out:
        extra = []
        if "ml_edge" in f:
            extra.append("ML %+.1fpp@%.2f" % (f["ml_edge"], f.get("ml_cuota", 0)))
        if "ou_edge" in f:
            extra.append("%s %+.1fpp@%.2f" % (f["ou_pick"], f["ou_edge"], f.get("ou_cuota", 0)))
        print("%-15s %-15s %-12s %4s%% %-6s %6.1f  %s" % (
            f["visitante"][:15], f["local"][:15], f["gana"][:12], f["prob_%"],
            "*" * f["estrellas"], f["total_est"], "  ".join(extra)))

    cols = ["visitante", "local", "gana", "prob_%", "confianza", "estrellas",
            "carreras_visit", "carreras_local", "total_est", "abridor_visit", "abridor_local",
            "ml_edge", "ml_cuota", "ou_pick", "ou_edge", "ou_cuota"]
    with io.open("kbo_ahora.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(filas_out)
    ruta_html = _html(filas_out)
    print("\nCSV : %s" % os.path.abspath("kbo_ahora.csv"))
    print("HTML: %s" % os.path.abspath(ruta_html))
    if not args.no_abrir:
        try:
            os.startfile(os.path.abspath(ruta_html))    # abre solo (Windows)
        except Exception:
            pass


def _estrellas_html(n):
    return '<span style="color:#e0b04a">%s</span><span style="color:#2a3949">%s</span>' % ("★" * n, "★" * (5 - n))


def _html(filas):
    tr = ""
    for f in filas:
        edge = []
        if "ml_edge" in f:
            cls = "pos" if f["ml_edge"] > 0 else "neg"
            edge.append('<span class="%s">ML %+.1fpp</span>' % (cls, f["ml_edge"]))
        if "ou_edge" in f:
            cls = "pos" if f["ou_edge"] > 0 else "neg"
            edge.append('<span class="%s">%s %+.1fpp</span>' % (cls, f["ou_pick"], f["ou_edge"]))
        conf_cls = {"Alta": "ca", "Media": "cm", "Baja": "cb"}[f["confianza"]]
        tr += ("<tr><td class=eq>{v} <span class=at>@</span> {l}<br><small>{pv} vs {pl}</small></td>"
               "<td class=pk>{g}</td><td>{p}%</td>"
               "<td class={cc}>{cn} {st}</td>"
               "<td>{cv}</td><td>{cl}</td><td class=tot>{t}</td>"
               "<td class=ed>{e}</td></tr>").format(
            v=f["visitante"], l=f["local"], pv=f["abridor_visit"], pl=f["abridor_local"],
            g=f["gana"], p=f["prob_%"], cc=conf_cls, cn=f["confianza"], st=_estrellas_html(f["estrellas"]),
            cv=f["carreras_visit"], cl=f["carreras_local"], t=f["total_est"],
            e=(" &middot; ".join(edge) if edge else "<span class=dim>—</span>"))
    html = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>KBO ahora</title><style>
:root{color-scheme:dark}body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0d1420;color:#e6edf4;margin:0}
.wrap{max-width:900px;margin:0 auto;padding:20px 14px 50px}h1{font-size:19px;margin:0 0 2px}
.sub{color:#8497ab;font-size:13px;margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{background:#141f2e;color:#8497ab;font-size:10px;letter-spacing:.03em;text-transform:uppercase;
padding:8px 6px;border-bottom:1px solid #2a3949;text-align:center}th:first-child{text-align:left}
td{padding:8px 6px;text-align:center;border-bottom:1px solid #1f2c3a;vertical-align:top}
td.eq{text-align:left;font-weight:600}td.eq small{color:#5d6e80;font-weight:400;font-size:10.5px}
.at{color:#5d6e80;font-weight:400}td.pk{font-weight:700;color:#4a9fd5}td.tot{font-weight:600}
td.ca{color:#4a9fd5;font-weight:600}td.cm{color:#8497ab}td.cb{color:#5d6e80}
td.ed{text-align:left;font-size:12px}.pos{color:#4a9fd5;font-weight:600}.neg{color:#d2755b}.dim{color:#5d6e80}
.ley{color:#5d6e80;font-size:11.5px;margin-top:14px;line-height:1.6}
</style></head><body><div class=wrap>
<h1>KBO &middot; predicci&oacute;n r&aacute;pida</h1>
<p class=sub>Log5 + Pythagenpat + FIP regresado (Marcel) + calibraci&oacute;n &middot; sobre tu historial real &middot; __GEN__</p>
<table><thead><tr><th>Partido / abridores</th><th>Gana</th><th>Prob</th><th>Confianza</th>
<th>C. visit</th><th>C. local</th><th>Total</th><th>Edge vs mercado</th></tr></thead>
<tbody>__ROWS__</tbody></table>
<p class=ley><b>Confianza</b>: combina el margen del modelo, la muestra, si ELO y carreras coinciden, y si hubo datos del abridor.<br>
<b>C. visit / local / Total</b>: carreras esperadas ya ajustadas por el pitcher abridor. &nbsp;
<b>Edge</b>: ventaja del modelo vs la cuota que pegaste (solo aparece si diste cuotas con #ml / #ou).</p>
</div></body></html>"""
    ruta = "kbo_ahora.html"
    io.open(ruta, "w", encoding="utf-8").write(
        html.replace("__GEN__", dt.datetime.now().strftime("%Y-%m-%d %H:%M")).replace("__ROWS__", tr))
    return ruta


if __name__ == "__main__":
    main()
