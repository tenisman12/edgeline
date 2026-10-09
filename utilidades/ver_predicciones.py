# -*- coding: utf-8 -*-
"""Muestra TODAS las predicciones de salida\\proximos.json, sin esconder ninguna.
Uso:  python utilidades\\ver_predicciones.py --ligas mlb,nhl --fecha 2026-09-30 --dias 2
      (sin --fecha: manana; sin --ligas: todas)
Cada juego: probabilidades de ambos lados, pick (siempre el favorito), carreras/goles esperados, total con Over/Under,
run line / puck line, cuotas y edge de TODOS los mercados con cuota, probables ESPN (contexto) y avisos.
* = pretemporada (aprox. por fecha; no cuenta para el historial). Sin ajuste por abridor/portero/lesiones."""
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse, datetime as dt, io, json, os

BASE = os.environ.get("EDGELINE_BASE", r"C:\Edgeline_repo")


def pct(x): return "%5.1f%%" % (100 * x) if x is not None else "   -  "


def es_pre(p):
    return bool(p.get("pretemporada"))      # lo marca plataforma.py (fecha de inicio de temporada regular)


def ab(t): return t.get("abrev") or t["nombre"].split()[-1]


def cuota(c): return "%+d" % c if c is not None else "-"


def _imp(o): return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def _nv(a, b):
    x, y = _imp(a), _imp(b); return x / (x + y)


def movimiento(c, v, h):
    """Movimiento de linea apertura -> actual (ESPN/DraftKings). Dinero implicito: hacia donde se movio la probabilidad sin margen."""
    out = []
    if None not in (c.get("ml_home"), c.get("ml_away"), c.get("ml_home_open"), c.get("ml_away_open")):
        a, b = _nv(c["ml_home_open"], c["ml_away_open"]), _nv(c["ml_home"], c["ml_away"])
        d = 100 * (b - a)
        lado = ab(h) if d > 0 else ab(v)
        out.append("ML %s %s / %s %s  ->  %s %s / %s %s   (prob. sin margen de %s: %.1f%% -> %.1f%%, %+.1f pts %s)" % (
            ab(v), cuota(c["ml_away_open"]), ab(h), cuota(c["ml_home_open"]), ab(v), cuota(c["ml_away"]), ab(h), cuota(c["ml_home"]),
            ab(h), 100 * a, 100 * b, d, ("hacia " + lado) if abs(d) >= 0.05 else "sin cambio"))
    if c.get("total") is not None and c.get("total_open") is not None:
        t0, t1 = c["total_open"], c["total"]
        out.append("TOTAL %.1f -> %.1f  %s" % (t0, t1, "(sin cambio)" if t0 == t1 else ("(sube %+.1f)" % (t1 - t0) if t1 > t0 else "(baja %+.1f)" % (t1 - t0))))
    if c.get("spread_home") is not None and c.get("spread_home_open") is not None:
        s0, s1 = c["spread_home_open"], c["spread_home"]
        out.append("SPREAD local %+g -> %+g  %s" % (s0, s1, "(sin cambio)" if s0 == s1 else ""))
    return out


def _f1(x, d=2):
    return ("%." + str(d) + "f") % x if isinstance(x, (int, float)) else "-"


def _forma_linea(nombre, f):
    if not f:
        return "      %-14s sin historial en tus datos" % nombre
    t = f.get("ventanas", {}).get("temp", {}); l10 = f.get("ventanas", {}).get("L10", {})
    rec = f.get("record", {})
    ult = "".join(x["r"] for x in f.get("ultimos10", []))
    osc = f.get("osciladores") or {}
    pw = f.get("power") or {}
    s = "      %-14s %s%s  racha %s  status %s  power %s/%s  record %s (L %s, V %s)" % (
        nombre, "[FUERA DE TEMPORADA] " if f.get("fuera_de_temporada") else "", f.get("temporada"), f.get("racha"),
        f.get("status"), pw.get("rank"), pw.get("de"), rec.get("temp"), rec.get("local") or "-", rec.get("visita") or "-")
    s += "\n      %-14s ult.10 (reciente primero) %s | L10 anota %s permite %s (ofensiva %s defensiva %s) | oscil. forma %+.2f ataque %s defensa %s -> %s" % (
        "", ult or "-", _f1(l10.get("gf")), _f1(l10.get("ga")), _f1(l10.get("of_idx")), _f1(l10.get("df_idx")),
        osc.get("forma", 0.0), _f1(osc.get("ataque"), 2), _f1(osc.get("defensa"), 2), osc.get("tendencia", "-"))
    return s


def _fx(x, d=2):
    return "-" if x is None else ("%.*f" % (d, x) if isinstance(x, float) else str(x))


def _bloque_tenis(d):
    """Una ventana del detalle de tenis -> 4 lineas: games, saque, resto, breaks."""
    if not d:
        return ["sin datos"]
    g, s, r, b = d.get("games") or {}, d.get("saque") or {}, d.get("resto") or {}, d.get("breaks") or {}
    return [
        "games: %s por partido (gana %s, pierde %s) %s%% games ganados | %s por set | tiebreaks %s | al maximo de sets %s%%" % (
            _fx(g.get("games_por_partido"), 1), _fx(g.get("games_ganados_pp"), 1), _fx(g.get("games_perdidos_pp"), 1),
            _fx(100 * g["pct_games_ganados"], 0) if g.get("pct_games_ganados") is not None else "-", _fx(g.get("games_por_set"), 1),
            _fx(g.get("tiebreaks_por_partido")), _fx(100 * g["pct_partidos_al_maximo_de_sets"], 0) if g.get("pct_partidos_al_maximo_de_sets") is not None else "-"),
        "saque: aces %s%% dobles faltas %s%% 1er saque %s%% | gana con 1er %s%% con 2do %s%% | puntos al saque %s%%" % (
            _pc(s.get("ace_pct")), _pc(s.get("doble_falta_pct")), _pc(s.get("primer_saque_pct")),
            _pc(s.get("gana_con_1er_saque")), _pc(s.get("gana_con_2do_saque")), _pc(s.get("puntos_ganados_al_saque"))),
        "resto: puntos al resto %s%% | gana vs 1er %s%% vs 2do %s%% | dominance %s" % (
            _pc(r.get("puntos_ganados_al_resto")), _pc(r.get("gana_vs_1er_saque_rival")),
            _pc(r.get("gana_vs_2do_saque_rival")), _fx(r.get("dominance_ratio"))),
        "breaks: hold %s%% | break %s%% | hace %s y concede %s por partido (total %s) | bp creados %s convertidos %s%% | bp salvados %s%%" % (
            _pc(b.get("hold_pct")), _pc(b.get("break_pct")), _fx(b.get("breaks_hechos_pp")), _fx(b.get("breaks_concedidos_pp")),
            _fx(b.get("breaks_totales_pp")), _fx(b.get("bp_creados_pp")), _pc(b.get("bp_convertidos_pct")), _pc(b.get("bp_salvados_pct")))]


def _pc(x):
    return "-" if x is None else "%.1f" % (100 * x)


def _forma_tenis_linea(nombre, f):
    if not f:
        return "      %-14s sin historial en tus datos" % nombre
    r12, r10 = f.get("record_12m", {}), f.get("record_L10", {})
    sup = ", ".join("%s %d-%d" % (k, v["w"], v["l"]) for k, v in (f.get("por_superficie_12m") or {}).items())
    pf = f.get("perfil") or {}
    ca = f.get("carga") or {}
    osc = f.get("osciladores") or {}
    rv = f.get("records_vs_12m") or {}
    out = ["      %-14s rank %s  racha %s  12m %s-%s  L10 %s-%s  por superficie: %s" % (
        nombre, f.get("ranking"), f.get("racha"), r12.get("w"), r12.get("l"), r10.get("w"), r10.get("l"), sup or "-"),
        "      %-14s mano %s, edad %s | carga: %s dias desde el ultimo, %s partidos y %s min en 14d | oscilador %s" % (
            "", pf.get("mano"), round(pf["edad"], 1) if isinstance(pf.get("edad"), (int, float)) else pf.get("edad"), ca.get("dias_desde_ultimo"), ca.get("partidos_14d"), ca.get("minutos_14d"),
            osc.get("tendencia", "-"))]
    if rv:
        out.append("      %-14s vs: %s" % ("", " | ".join("%s %s-%s" % (k, v.get("w"), v.get("l")) for k, v in rv.items() if isinstance(v, dict))))
    return "\n".join(out)


def _tenis_estadisticas(p, completo):
    ee = p.get("estadisticas_equipo") or {}
    h, v = p["home"], p["away"]
    for lado, t in (("away", v), ("home", h)):
        x = ee.get(lado)
        if not x:
            continue
        ventanas = [("L10", x.get("L10")), ("12m", x.get("12m"))]
        if x.get("superficie_hoy") is not None:
            ventanas.append(("superficie de hoy 12m", x.get("superficie_hoy")))
        if completo:
            ventanas.insert(0, ("L5", x.get("L5")))
            for k, d in (x.get("superficie_12m") or {}).items():
                ventanas.append(("superficie %s 12m" % k, d))
            for k, d in (x.get("formato_12m") or {}).items():
                ventanas.append(("formato %s 12m" % k.replace("_", " "), d))
        for nom, d in ventanas:
            print("      ESTADISTICAS %-4s [%s]" % (ab(t), nom))
            for ln in _bloque_tenis(d):
                print("            " + ln)


def _jug_resumen(lado, j):
    if not j or not j.get("disponible"):
        return ["      %-5s no disponible: %s" % (lado, (j or {}).get("motivo", "-"))]
    out = ["      %-5s (jugadores hasta %s)" % (lado, j.get("ultimo_juego"))]
    pr = j.get("probable")
    if pr:
        r = pr.get("resumen_ultimas5") or {}
        out.append("            abridor %s: ult.5 salidas IP %s ERA %s WHIP %s K/9 %s" % (
            pr.get("jugador"), r.get("ip"), r.get("era"), r.get("whip"), r.get("k9")) if r else
            "            abridor %s: %s" % (pr.get("jugador"), pr.get("nota")))
    if j.get("bullpen"):
        b = j["bullpen"]
        out.append("            bullpen ult.3 dias: %s lanzamientos, %s relevistas usados" % (b.get("pitches_total"), b.get("relevistas_usados")))
    if j.get("bateadores"):
        out.append("            bateadores (ult.14): " + "; ".join("%s %s/%s/%s" % (x["jugador"], x["avg"], x["hr"], x["rbi"]) for x in j["bateadores"]["jugadores"][:5]) + "  (avg/HR/RBI)")
    if j.get("porteros"):
        out.append("            porteros (ult.10): " + "; ".join("%s sv%% %s aperturas %s" % (x["jugador"], x["sv_pct"], x["aperturas"]) for x in j["porteros"]["jugadores"]))
    if j.get("patinadores"):
        out.append("            patinadores (ult.10): " + "; ".join("%s %dG %dA" % (x["jugador"], x["g"], x["a"]) for x in j["patinadores"]["jugadores"][:5]))
    for k, tit in (("qb", "QB"), ("rb", "RB"), ("receptores", "receptores")):
        if j.get(k):
            out.append("            %s: " % tit + "; ".join("%s %s" % (x["jugador"], ", ".join("%s %s" % (a, b) for a, b in x.items() if a not in ("jugador", "pos", "juegos"))) for x in j[k]))
    if j.get("jugadores"):
        out.append("            por minutos/titularidad (ult.%s, criterio %s): " % (j.get("ventana_juegos"), j.get("criterio")) +
                   "; ".join(x["jugador"] for x in j["jugadores"][:8]))
    return out


def imprimir_bloques(p, completo=False):
    """Mismos bloques en todos los deportes: validacion, forma, h2h, estadisticas, jugadores, disponibilidad."""
    h, v = p["home"], p["away"]
    val = p.get("validacion") or {}
    if val:
        print("      VALIDACION  " + " | ".join("%s %s" % (k, val[k].replace("_", " ")) for k in ("Ganador", "Total", "Spread", "Breaks") if k in val))
    em = p.get("emparejado") or {}
    if em:
        print("      NOMBRES EN TUS DATOS  %s = %s | %s = %s" % (ab(v), em.get("away") or "SIN EMPATE", ab(h), em.get("home") or "SIN EMPATE"))
    fo = p.get("forma") or {}
    if fo.get("home") or fo.get("away"):
        print("      FORMA")
        if p.get("tipo") == "tenis":
            print(_forma_tenis_linea(ab(v), fo.get("away"))); print(_forma_tenis_linea(ab(h), fo.get("home")))
        else:
            print(_forma_linea(ab(v), fo.get("away"))); print(_forma_linea(ab(h), fo.get("home")))
    hd = p.get("h2h_datos") or {}
    if hd.get("partidos"):
        if p.get("tipo") == "tenis":
            print("      H2H (tus datos) %s %d - %d %s" % (ab(h), hd.get("gana_a", 0), hd.get("gana_b", 0), ab(v)))
        else:
            print("      H2H (tus datos) %d juegos: %s %d - %d %s%s" % (hd["partidos"], ab(h), hd.get("gana_a", 0), hd.get("gana_b", 0), ab(v),
                  (" (%d empates)" % hd["empates"]) if hd.get("empates") else ""))
    ee = p.get("estadisticas_equipo") or {}
    if p.get("tipo") == "tenis":
        _tenis_estadisticas(p, completo)
    elif ee.get("home") or ee.get("away"):
        for lado, t in (("away", v), ("home", h)):
            x = ee.get(lado) or {}
            l10 = x.get("L10") or {}
            if l10:
                n = len(l10)
                print("      ESTADISTICAS %-4s %d columnas (%s) | %s" % (ab(t), n, ee.get("fuente"),
                      ", ".join("%s %s" % (k, val_) for k, val_ in list(l10.items())[: (n if completo else 8)])))
    jc = p.get("jugadores_clave")
    if jc:
        print("      JUGADORES CLAVE")
        for lado, t in (("away", v), ("home", h)):
            for linea_ in _jug_resumen(ab(t), jc.get(lado)): print(linea_)
    bl = p.get("bloques") or {}
    falt = ["%s (%s)" % (k, x.get("motivo")) for k, x in bl.items() if not x.get("ok")]
    print("      BLOQUES %d/%d disponibles%s" % (sum(1 for x in bl.values() if x.get("ok")), len(bl),
          ("  | no disponibles: " + "; ".join(falt)) if falt else ""))


def _mercados_futbol(d, h, v):
    """Todos los mercados derivados del modelo de futbol, cada uno con su estado de validacion."""
    val = d.get("_validacion") or {}
    def f(k, nombre):
        if d.get(k) is None: return None
        return "%-24s %6s  %s" % (nombre, pct(d[k]).strip(), "" if val.get(k) == "publicable" else "(modelo debajo de la base)")
    filas = [("1X", "Doble oport. %s o empate" % ab(h)), ("X2", "Doble oport. %s o empate" % ab(v)), ("12", "Doble oport. sin empate"),
             ("aa_si", "Ambos anotan SI"), ("aa_no", "Ambos anotan NO"),
             ("over_1.5", "Over 1.5"), ("over_2.5", "Over 2.5"), ("over_3.5", "Over 3.5"),
             ("local_gana_por_2", "%s gana por 2+" % ab(h)), ("visita_gana_por_2", "%s gana por 2+" % ab(v)),
             ("1T_1", "1er tiempo: gana %s" % ab(h)), ("1T_X", "1er tiempo: empate"), ("1T_2", "1er tiempo: gana %s" % ab(v)),
             ("1T_over_0.5", "1er tiempo Over 0.5"), ("1T_over_1.5", "1er tiempo Over 1.5")]
    print("      MERCADOS DE FUTBOL (del mismo modelo; cada uno con su validacion)")
    for k, n in filas:
        t = f(k, n)
        if t: print("        " + t)
    if d.get("marcadores_top"):
        print("        Marcadores mas probables: " + ", ".join("%s (%s)" % (x["marcador"], pct(x["p"]).strip()) for x in d["marcadores_top"]))
    if d.get("corners_esperados"):
        print("        CORNERS esperados %.1f:  " % d["corners_esperados"] + "  ".join("O%s %s%s" % (l, pct(d["corners_over_%s" % l]).strip(), "" if val.get("corners_over_%s" % l) == "publicable" else "*") for l in ("8.5", "9.5", "10.5", "11.5")))
    if d.get("tarjetas_esperadas"):
        print("        TARJETAS esperadas %.1f: " % d["tarjetas_esperadas"] + "  ".join("O%s %s%s" % (l, pct(d["tarjetas_over_%s" % l]).strip(), "" if val.get("tarjetas_over_%s" % l) == "publicable" else "*") for l in ("2.5", "3.5", "4.5", "5.5")))
    print("        (* o '(modelo debajo de la base)' = no supera a la linea base en esa liga)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ligas"); ap.add_argument("--fecha"); ap.add_argument("--dias", type=int, default=1)
    ap.add_argument("--completo", action="store_true", help="imprime TODAS las columnas de estadisticas de equipo")
    ap.add_argument("--valor", action="store_true", help="agrega el apartado VALOR (edge y Kelly por mercado); sin esta opcion no se muestra")
    ap.add_argument("--archivo", default=os.path.join(BASE, "salida", "proximos.json"))
    a = ap.parse_args()
    with io.open(a.archivo, encoding="utf-8") as f:
        d = json.load(f)
    f0 = dt.date.fromisoformat(a.fecha) if a.fecha else dt.date.today() + dt.timedelta(days=1)
    fechas = [(f0 + dt.timedelta(days=i)).isoformat() for i in range(a.dias)]
    ligas = {x.strip().lower() for x in a.ligas.split(",")} if a.ligas else None
    print("Predicciones (proximos.json generado %s) | * = pretemporada | horas CDMX\n" % d.get("generado"))
    hubo = False
    for fe in fechas:
        ps_dia = [p for p in d["partidos"] if p["fecha"] == fe and (ligas is None or p["liga"] in ligas)]
        for lg in sorted({p["liga"] for p in ps_dia}):
            hubo = True
            print("=" * 100); print("%s  %s" % (lg.upper(), fe)); print("=" * 100)
            for p in [x for x in ps_dia if x["liga"] == lg]:
                m = p.get("modelo"); h, v = p["home"], p["away"]
                pre = "  [PRETEMPORADA]" if es_pre(p) else ""
                print("\n%s%s  %s @ %s%s   %s" % ("*" if pre else " ", p["hora"], v["nombre"], h["nombre"], pre, p.get("nota") or ""))
                if p.get("serie"): print("      serie: %s" % p["serie"])
                if not m:
                    print("      modelo: sin datos suficientes (%s)" % p.get("motivo")); imprimir_bloques(p, a.completo); continue
                u = m.get("unidad", "")
                print("      PROBABILIDAD  %-4s %s   %-4s %s" % (ab(v), pct(m["p_away"]), ab(h), pct(m["p_home"])))
                gw = p.get("ganador") or {}
                print("      GANA          %s" % (gw.get("nombre") or "-"))
                if m.get("x_away") is not None and m.get("x_home") is not None:
                    print("      %-13s %-4s %.2f   %-4s %.2f   total %.2f" % (u.upper() + " ESP.", ab(v), m["x_away"], ab(h), m["x_home"], m["total"]))
                else:
                    print("      %-13s total %.2f" % (u.upper() + " ESP.", m["total"]))
                if m.get("linea_total"):
                    print("      TOTAL %.1f (%s%s)   Over %s   Under %s" % (
                        m["linea_total"], "linea de mercado" if m.get("linea_es_mercado") else "linea de referencia",
                        ", total: modelo debajo de la base" if (p.get("validacion") or {}).get("Total") == "sin_validar" else "",
                        pct(m.get("p_over")).strip(), pct(1 - m["p_over"] if m.get("p_over") is not None else None).strip()))
                else:
                    print("      TOTAL sin linea publicada todavia (modelo %.2f)" % m["total"])
                sp = m.get("spread")
                if sp and sp.get("linea_home") is not None:
                    nom = {"beisbol": "RUN LINE", "hockey": "PUCK LINE", "futbol": "HANDICAP"}.get(p.get("deporte"), "SPREAD")
                    print("      %s %+g %s (%s%s)   %s %s   %s %s" % (
                        nom, sp["linea_home"], ab(h), "linea de mercado" if sp.get("linea_es_mercado") else "linea de referencia",
                        ", modelo debajo de la base" if (p.get("validacion") or {}).get("Spread") == "sin_validar" else "",
                        ab(h), pct(sp.get("p_home")).strip(), ab(v), pct(sp.get("p_away")).strip()))
                for nom, pr in m.get("extra") or []:
                    es_prob = isinstance(pr, float) and 0 <= pr <= 1 and ("rob" in nom or "%" in nom or "line" in nom.lower())
                    print("      %-26s %s" % (nom, pct(pr).strip() if es_prob else pr))
                if m.get("derivados"): _mercados_futbol(m["derivados"], h, v)
                if m.get("nota"): print("      nota: %s" % m["nota"])
                c = p.get("cuotas")
                if c:
                    print("      CUOTAS (%s): ML %s %s / %s %s | total %s over %s under %s" % (
                        c.get("casa"), ab(v), cuota(c.get("ml_away")), ab(h), cuota(c.get("ml_home")),
                        c.get("total"), cuota(c.get("over_odds")), cuota(c.get("under_odds"))))
                    for t in movimiento(c, v, h): print("      MOVIMIENTO  " + t)
                    if a.valor:
                        print("      VALOR (apartado aparte: modelo contra mercado)")
                        print("      %-22s %-9s %8s %9s %9s %8s %7s" % ("MERCADO", "lado", "cuota", "p modelo", "p mercado", "edge", "kelly"))
                        for x in p.get("mercados") or []:
                            print("      %-22s %-9s %8s %9s %9s %+7.1f%% %6.1f%%%s" % (
                                x["mercado"], x["lado"], cuota(x["cuota"]), pct(x["p_modelo"]).strip(), pct(x["p_mercado"]).strip(),
                                100 * x["edge"], 100 * (x.get("kelly") or 0.0),
                                "  <- VALOR" if x.get("estado") == "valor" else ("  (dif.: en este mercado el modelo no vence al baseline)" if x.get("estado") == "sin_validar" else ("  (cuota < 1.70: no se marca)" if x.get("estado") == "cuota_baja" else ""))))
                else:
                    print("      CUOTAS: aun no publicadas")
                if a.valor and p.get("picks"):
                    print("      PICK PREMIUM (puntaje 0-100: precio, modelo, forma/osciladores, movimiento, consenso, H2H, contexto)")
                    print("      %-7s %5s %-22s %-18s %8s %-10s %7s %7s %5s  %s" % ("NIVEL", "pts", "MERCADO", "pick", "cuota", "casa", "p final", "EV", "stake", "senales / razones"))
                    for k in sorted(p["picks"], key=lambda z: -z["puntaje"]):
                        if k["nivel"] == "pasar" and not a.completo: continue
                        print("      %-7s %5.1f %-22s %-18s %8s %-10s %6.1f%% %7s %4.1fu  %s%s" % (
                            k["nivel"], k["puntaje"], k["mercado"], k["texto"][:18],
                            cuota(k["cuota"]) if k["cuota"] is not None else ("min %.2f" % (k["cuota_min"] or 0)), (k["casa"] or "")[:10],
                            100 * k["p_final"], ("%+.1f%%" % (100 * k["ev"])) if k["ev"] is not None else "-", k["stake"],
                            " ".join("%s=%s" % (x, y) for x, y in k["senales"].items() if y is not None),
                            ("  | " + "; ".join(k["razones"])) if k["razones"] else ""))
                pj = [x for x in (v.get("probable"), h.get("probable")) if x]
                if pj: print("      probables ESPN (contexto, no se aplican): %s / %s" % (v.get("probable") or "?", h.get("probable") or "?"))
                if p.get("alerta") and (a.valor or p.get("pretemporada")): print("      AVISO: %s" % p["alerta"])
                imprimir_bloques(p, a.completo)
    if not hubo:
        print("No hay partidos en esas fechas/ligas.")
        fs = sorted({p["fecha"] for p in d["partidos"] if ligas is None or p["liga"] in ligas})
        if fs: print("Fechas con partidos en el archivo: %s" % ", ".join(fs[:12]))
    if d.get("avisos"):
        print("\nAvisos del modelo:"); [print("  - " + x) for x in d["avisos"]]


if __name__ == "__main__":
    main()
