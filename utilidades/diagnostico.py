# -*- coding: utf-8 -*-
"""
utilidades/diagnostico.py - DIAGNOSTICO COMPLETO de Edgeline en un solo comando.

Lee (no modifica nada) tus datos, las predicciones publicadas, los snapshots de cuotas, el historial de picks y
los workflows, y escribe el informe en  salida\\diagnostico.txt  (y  salida\\diagnostico.json).
Ese .txt es lo que se le pasa a Claude para validar.

Uso (en C:\\Edgeline_repo, con $env:EDGELINE_BASE = "C:\\Edgeline_repo"):
    python utilidades\\diagnostico.py
    python utilidades\\diagnostico.py --partidos      # agrega una linea por partido (largo)

Solo stdlib. Tarda menos de un minuto.
"""
import argparse, collections, csv, datetime as dt, glob, json, os, subprocess, sys

csv.field_size_limit(10 ** 8)
BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOY = dt.date.today()
OUT = []
ALERTAS = []          # (nivel, texto)  nivel = FALLO | AVISO


def p(txt=""):
    OUT.append(txt)


def titulo(t):
    p(""); p("=" * 100); p(t); p("=" * 100)


def alerta(nivel, txt):
    ALERTAS.append((nivel, txt))


def dias_desde(f):
    try:
        f = str(f)
        f = "%s-%s-%s" % (f[:4], f[4:6], f[6:8]) if len(f) == 8 and f.isdigit() else f[:10]
        return (HOY - dt.date.fromisoformat(f)).days
    except Exception:
        return None


def leer(ruta):
    """-> (columnas, generador de filas); el archivo se abre aparte para cada lectura."""
    with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
        cols = csv.DictReader(fh).fieldnames or []

    def filas():
        with open(ruta, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                yield r
    return cols, filas()


def sh(cmd):
    try:
        r = subprocess.run(cmd, cwd=BASE, capture_output=True, timeout=30, text=True, encoding="utf-8", errors="replace")
        return (r.stdout or "").strip()
    except Exception:
        return ""


# ------------------------------------------------------------------ A. entorno
def a_entorno():
    titulo("A. ENTORNO")
    p("Fecha del diagnostico : %s" % dt.datetime.now().isoformat(timespec="seconds"))
    p("BASE                  : %s" % BASE)
    p("Python                : %s" % sys.version.split()[0])
    br = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"]); ult = sh(["git", "log", "-1", "--format=%h %ad %s", "--date=short"])
    cambios = sh(["git", "status", "--short"])
    p("Git rama / ultimo     : %s | %s" % (br or "(sin git)", ult or "-"))
    p("Git cambios sin subir : %d archivos" % (len(cambios.splitlines()) if cambios else 0))
    if cambios:
        alerta("AVISO", "hay %d archivos con cambios sin commit (git status)" % len(cambios.splitlines()))
    for d in ("datos", "nucleo", "nucleo/_calib", "colectores", "utilidades", "salida", ".github/workflows"):
        ok = os.path.isdir(os.path.join(BASE, d))
        p("  carpeta %-20s %s" % (d, "ok" if ok else "FALTA"))
        if not ok:
            alerta("FALLO", "falta la carpeta %s" % d)
    for w in ("actualizar.yml", "cuotas.yml"):
        ruta = os.path.join(BASE, ".github", "workflows", w)
        if os.path.exists(ruta):
            t = open(ruta, encoding="utf-8", errors="replace").read()
            claves = [k for k in ("plataforma.py", "actualizar_todo.py", "jugadores_recientes.py", "snapshot_cuotas.py", "cron") if k in t]
            p("  workflow %-16s presente | contiene: %s" % (w, ", ".join(claves) or "-"))
        else:
            p("  workflow %-16s FALTA" % w); alerta("FALLO", "falta .github/workflows/%s" % w)


# ------------------------------------------------------------------ B. datos historicos
DATOS = {  # archivo: (columna fecha, columna liga/segmento, columnas clave de duplicado, desfase tolerado en dias)
    "beisbol.csv": ("game_date", "league", ("gamePk", "team"), 3),
    "futbol.csv": ("game_date", "league", ("gamePk", "team"), 9),
    "hockey.csv": ("game_date", None, ("gamePk", "team"), 9),
    "nba.csv": ("game_date", None, ("gamePk", "team"), 200),
    "americano.csv": ("game_date", None, ("gamePk", "team"), 9),
    "tenis.csv": ("tourney_date", "tour", ("tourney_id", "round", "winner_name", "loser_name"), 5),
}


def b_datos():
    titulo("B. DATOS HISTORICOS (datos\\*.csv)")
    p("%-14s %9s %5s %-12s %-12s %8s %9s  %s" % ("archivo", "filas", "cols", "primera", "ultima", "atraso_d", "dup_clave", "estado"))
    for n, (cf, cl, claves, tol) in DATOS.items():
        ruta = os.path.join(BASE, "datos", n)
        if not os.path.exists(ruta):
            p("%-14s NO EXISTE" % n); alerta("FALLO", "datos\\%s no existe" % n); continue
        cols, rd = leer(ruta)
        filas = fmin = fmax = None
        n_f = 0; vistos = set(); dup = 0; muestra = []; segs = collections.defaultdict(lambda: [None, None, 0]); sin_fecha = 0
        usa_claves = all(k in cols for k in claves)
        for r in rd:
            n_f += 1
            f = (r.get(cf) or "")[:10] if cf in cols else ""
            if not f:
                sin_fecha += 1
            else:
                fmin = f if fmin is None or f < fmin else fmin
                fmax = f if fmax is None or f > fmax else fmax
            if usa_claves:
                k = tuple(r.get(c) for c in claves)
                if k in vistos:
                    dup += 1
                    if len(muestra) < 8:
                        muestra.append((k, f, r.get("score"), r.get("match_num")))
                else:
                    vistos.add(k)
            if cl and cl in cols:
                s = segs[r.get(cl) or "?"]
                s[2] += 1
                if f:
                    s[0] = f if s[0] is None or f < s[0] else s[0]
                    s[1] = f if s[1] is None or f > s[1] else s[1]
        atraso = dias_desde(fmax) if fmax else None
        est = "ok"
        if dup:
            est = "DUPLICADOS"; alerta("FALLO", "datos\\%s tiene %d filas duplicadas por clave %s" % (n, dup, "+".join(claves)))
        elif atraso is not None and atraso > tol:
            est = "ATRASADO"; alerta("AVISO", "datos\\%s: ultima fecha %s (%d dias de atraso; tolerado %d)" % (n, fmax, atraso, tol))
        if sin_fecha:
            alerta("AVISO", "datos\\%s: %d filas sin fecha" % (n, sin_fecha))
        p("%-14s %9d %5d %-12s %-12s %8s %9s  %s" % (n, n_f, len(cols), fmin, fmax, atraso if atraso is not None else "-", dup if usa_claves else "n/a", est))
        for k, f, sc, mn in muestra:
            p("    duplicado: %s | fecha %s | score %s | match_num %s" % ("/".join(str(z) for z in k), f, sc, mn))
        for sg, (a, b, c) in sorted(segs.items()):
            p("    %-22s %8d filas  %s -> %s  (atraso %s d)" % (sg, c, a, b, dias_desde(b)))
    # archivos de equipos y mercado
    for carpeta in ("equipos", "mercado"):
        d = os.path.join(BASE, "datos", carpeta)
        if not os.path.isdir(d):
            p("datos\\%s: no existe" % carpeta); continue
        p(""); p("datos\\%s\\" % carpeta)
        for ruta in sorted(glob.glob(os.path.join(d, "*.csv"))):
            cols, rd = leer(ruta)
            fe = next((c for c in ("game_date", "fecha", "date") if c in cols), None)
            nf = 0; fx = None
            for r in rd:
                nf += 1
                if fe and r.get(fe):
                    f = r[fe][:10]; fx = f if fx is None or f > fx else fx
            p("  %-34s %8d filas  ultima %s  (atraso %s d)" % (os.path.basename(ruta), nf, fx, dias_desde(fx) if fx else "-"))
            if carpeta == "equipos" and fx and (dias_desde(fx) or 0) > 45:
                alerta("AVISO", "datos\\equipos\\%s: ultima fecha %s (%d dias); si esa liga esta en temporada, su forma y estadisticas salen viejas" % (
                    os.path.basename(ruta), fx, dias_desde(fx)))


# ------------------------------------------------------------------ C. jugadores
def c_jugadores():
    titulo("C. JUGADORES (datos\\jugadores y datos\\jugadores_recientes)")
    for carpeta, nom in (("jugadores", "COMPLETO (solo en tu PC)"), ("jugadores_recientes", "RECIENTES (viaja a GitHub)")):
        d = os.path.join(BASE, "datos", carpeta)
        p("%s  %s" % (nom, d))
        if not os.path.isdir(d):
            p("  (no existe)")
            if carpeta == "jugadores_recientes":
                alerta("AVISO", "datos\\jugadores_recientes no existe: Actions arrancara sin jugadores")
            continue
        for ruta in sorted(glob.glob(os.path.join(d, "*.csv"))):
            cols, rd = leer(ruta)
            nf = 0; fx = fm = None; kg = set()
            for r in rd:
                nf += 1
                f = (r.get("game_date") or "")[:10]
                if f:
                    fx = f if fx is None or f > fx else fx
                    fm = f if fm is None or f < fm else fm
            p("  %-34s %9d filas  %s -> %s  (atraso %s d)  %.1f MB" % (os.path.basename(ruta), nf, fm, fx, dias_desde(fx) if fx else "-", os.path.getsize(ruta) / 1048576))
        raw = os.path.join(d, "raw")
        if os.path.isdir(raw):
            p("  raw: %d archivos" % sum(len(f) for _, _, f in os.walk(raw)))


# ------------------------------------------------------------------ D. modelos calibrados
def d_calib():
    titulo("D. CALIBRACIONES DE LOS MODELOS (nucleo\\_calib)")
    d = os.path.join(BASE, "nucleo", "_calib")
    if not os.path.isdir(d):
        p("(no existe)"); alerta("FALLO", "nucleo\\_calib no existe"); return
    for ruta in sorted(glob.glob(os.path.join(d, "*"))):
        p("  %-40s %8.1f KB  modificado %s" % (os.path.basename(ruta), os.path.getsize(ruta) / 1024,
                                              dt.datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d")))


# ------------------------------------------------------------------ E. predicciones
def e_pred(por_partido):
    titulo("E. PREDICCIONES PUBLICADAS (salida\\proximos.json)")
    ruta = os.path.join(BASE, "salida", "proximos.json")
    if not os.path.exists(ruta):
        p("No existe salida\\proximos.json"); alerta("FALLO", "no existe salida\\proximos.json (corre plataforma.py)"); return None
    d = json.load(open(ruta, encoding="utf-8"))
    ps = d.get("partidos") or []
    gen = d.get("generado")
    p("generado: %s | version de ficha: %s | partidos: %d | sin modelo: %d | umbral edge %s" % (
        gen, d.get("ficha"), len(ps), len(d.get("sin_modelo") or []), d.get("umbral_edge")))
    ed = dias_desde(gen)
    if ed is not None and ed > 1:
        alerta("AVISO", "proximos.json tiene %d dias de antiguedad" % ed)
    if d.get("ficha") != 2:
        alerta("FALLO", "proximos.json no es ficha 2 (version %s): falta correr plataforma.py con el codigo nuevo" % d.get("ficha"))
    for a in d.get("avisos") or []:
        p("  aviso del modelo: %s" % a); alerta("AVISO", "aviso del modelo: %s" % a)

    por = collections.defaultdict(list)
    for x in ps:
        por[x["liga"]].append(x)
    p(""); p("%-10s %6s %7s %6s %5s %6s %7s %6s  %s" % ("liga", "juegos", "modelo", "sin", "pre", "valor", "cuotas", "TBD", "fechas"))
    for lg, xs in sorted(por.items()):
        con = [x for x in xs if x.get("modelo")]
        pre = sum(1 for x in xs if x.get("pretemporada"))
        val = sum(1 for x in xs if x.get("valor"))
        cu = sum(1 for x in xs if x.get("cuotas"))
        tbd = sum(1 for x in xs if "TBD" in ((x["home"].get("nombre") or "").upper(), (x["away"].get("nombre") or "").upper()))
        fs = sorted({x["fecha"] for x in xs})
        p("%-10s %6d %7d %6d %5d %6d %7d %6d  %s" % (lg, len(xs), len(con), len(xs) - len(con), pre, val, cu, tbd, ", ".join(fs[:4])))

    p(""); p("MOTIVOS por los que un partido no tiene prediccion:")
    mot = collections.Counter()
    for x in ps:
        if not x.get("modelo"):
            m = (x.get("motivo") or "?")
            if ":" in m and "TBD" not in m:
                m = m.split(":")[0]
            mot[(x["liga"], m[:80])] += 1
    for (lg, m), c in mot.most_common(25):
        p("  %-8s %4d  %s" % (lg, c, m))
        if "sin modelo para esta liga" in m or "modelo no disponible" in m:
            alerta("AVISO", "%s: %d partidos '%s'" % (lg, c, m))

    p(""); p("BLOQUES de la ficha (partidos con el bloque disponible / total) por liga:")
    nombres = ["prediccion", "totales", "spread", "forma", "estadisticas_equipo", "jugadores_clave", "movimiento", "mercado", "contexto"]
    p("%-10s " % "liga" + " ".join("%-10s" % n[:10] for n in nombres))
    for lg, xs in sorted(por.items()):
        fila = []
        for n in nombres:
            ok = sum(1 for x in xs if (x.get("bloques") or {}).get(n, {}).get("ok"))
            fila.append("%4d/%-5d" % (ok, len(xs)))
        p("%-10s " % lg + " ".join(fila))
    errs = [(x["liga"], x["id"], x["bloques"]["error"]["motivo"]) for x in ps if (x.get("bloques") or {}).get("error")]
    for lg, i, m in errs[:15]:
        p("  ERROR de ficha: %s %s -> %s" % (lg, i, m))
    if errs:
        alerta("FALLO", "%d partidos con error al armar la ficha (ver lista)" % len(errs))
    sinficha = [x for x in ps if "bloques" not in x]
    if sinficha:
        alerta("FALLO", "%d partidos sin bloque 'bloques' (JSON viejo)" % len(sinficha))

    # motivos de bloques no disponibles (agrupados)
    p(""); p("Motivos de bloques NO disponibles (liga, bloque, motivo, n):")
    cm = collections.Counter()
    for x in ps:
        for n, b in (x.get("bloques") or {}).items():
            if not b.get("ok") and n not in ("mercado", "contexto", "movimiento", "spread", "totales"):
                cm[(x["liga"], n, (b.get("motivo") or "")[:70])] += 1
    for (lg, n, m), c in cm.most_common(25):
        p("  %-8s %-20s %4d  %s" % (lg, n, c, m))

    # empate de nombres
    sin_emp = [(x["liga"], x["home"]["nombre"], x["away"]["nombre"], x["emparejado"]) for x in ps
               if x.get("emparejado") and (not x["emparejado"].get("home") or not x["emparejado"].get("away"))]
    p(""); p("Equipos sin empate en tus datos: %d" % len(sin_emp))
    for s in sin_emp[:20]:
        p("  %s: %s vs %s -> %s" % s)
    if sin_emp:
        alerta("AVISO", "%d partidos con algun equipo sin empate en tus datos" % len(sin_emp))
    # nombres dudosos: el nombre empatado no comparte ninguna palabra con el de ESPN
    dud = []
    for x in ps:
        em = x.get("emparejado") or {}
        for lado in ("home", "away"):
            a = (x[lado].get("nombre") or "").lower().split(); b = (em.get(lado) or "").lower().split()
            if b and not (set(a) & set(b)) and (x[lado].get("abrev") or "").lower() != (em.get(lado) or "").lower() \
                    and not ((em.get(lado) or "").isupper() and len(em.get(lado) or "") <= 4):
                dud.append((x["liga"], x[lado]["nombre"], em.get(lado)))
    p("Empates dudosos (sin palabras en comun): %d" % len(dud))
    for s in sorted(set(dud))[:20]:
        p("  %s: ESPN '%s' -> datos '%s'" % s)
    if dud:
        alerta("AVISO", "%d empates de nombre dudosos (ver seccion E)" % len(set(dud)))

    # sanidad numerica
    p(""); p("SANIDAD de los numeros:")
    malas = []; tot_raros = []; edge_alto = []; pgan_ext = []
    for x in ps:
        m = x.get("modelo")
        if not m:
            continue
        ph, pa, pd = m.get("p_home"), m.get("p_away"), m.get("p_draw") or 0.0
        if ph is None or pa is None or not (0 <= ph <= 1 and 0 <= pa <= 1) or abs(ph + pa + pd - 1) > 0.02:
            malas.append((x["liga"], x["id"], ph, pa, pd))
        if max(ph or 0, pa or 0) > 0.90:
            pgan_ext.append((x["liga"], x["home"]["nombre"], x["away"]["nombre"], round(max(ph, pa), 3)))
        lt, t = m.get("linea_total"), m.get("total")
        if lt and t and abs(t - lt) / lt > 0.25:
            tot_raros.append((x["liga"], x["home"]["nombre"], x["away"]["nombre"], t, lt))
        for mk in x.get("mercados") or []:
            if mk.get("edge") is not None and mk["edge"] > 0.15:
                edge_alto.append((x["liga"], x["home"]["nombre"], x["away"]["nombre"], mk["mercado"], mk["lado"], round(mk["edge"], 3)))
    p("  probabilidades que no suman 1 o fuera de 0-1 : %d" % len(malas))
    for s in malas[:10]:
        p("     %s" % (s,))
    if malas:
        alerta("FALLO", "%d partidos con probabilidades invalidas" % len(malas))
    p("  favorito con mas de 90%% (revisar)             : %d" % len(pgan_ext))
    for s in pgan_ext[:10]:
        p("     %s" % (s,))
    p("  total del modelo a >25%% de la linea           : %d" % len(tot_raros))
    for s in tot_raros[:10]:
        p("     %s: %s vs %s modelo %.2f linea %.1f" % s)
    p("  edge > 15%% en algun mercado                   : %d" % len(edge_alto))
    for s in edge_alto[:12]:
        p("     %s: %s vs %s %s %s edge %+.1f%%" % (s[:5] + (100 * s[5],)))
    if edge_alto:
        alerta("AVISO", "%d mercados con edge > 15%% (casi siempre falta informacion que el mercado ya conoce)" % len(edge_alto))

    # validacion por liga
    p(""); p("VALIDACION por liga (estado publicado de cada mercado):")
    vv = collections.defaultdict(lambda: collections.Counter())
    for x in ps:
        for k, v in (x.get("validacion") or {}).items():
            vv[(x["liga"], k)][v] += 1
    for (lg, k), c in sorted(vv.items()):
        p("  %-10s %-8s %s" % (lg, k, ", ".join("%s %d" % (a, b) for a, b in c.items())))

    inc = [x for x in ps if not x.get("modelo") and any(v == "publicable" for v in (x.get("validacion") or {}).values())]
    if inc:
        alerta("AVISO", "%d partidos sin modelo muestran algun mercado como 'publicable' (debe decir sin_modelo)" % len(inc))
    # pretemporada que se colo
    pre_ini = {"nhl": "2026-10-07"}
    for x in ps:
        pi = pre_ini.get(x["liga"])
        if pi and x["fecha"] < pi and not x.get("pretemporada"):
            alerta("FALLO", "%s %s vs %s (%s) esta antes del inicio de temporada (%s) y NO esta marcado pretemporada" % (
                x["liga"], x["home"]["nombre"], x["away"]["nombre"], x["fecha"], pi)); break
    # ganador/pick
    sin_g = sum(1 for x in ps if x.get("modelo") and not x.get("ganador"))
    if sin_g:
        alerta("FALLO", "%d partidos con modelo pero sin campo 'ganador'" % sin_g)

    if por_partido:
        p(""); p("PARTIDOS (liga fecha hora visita @ local | prob | bloques ok | motivo)")
        for x in sorted(ps, key=lambda z: (z["liga"], z["fecha"], z.get("hora") or "")):
            m = x.get("modelo") or {}
            ok = sum(1 for b in (x.get("bloques") or {}).values() if b.get("ok"))
            p("  %-7s %s %s %s @ %s | %s/%s | %d/%d | %s" % (
                x["liga"], x["fecha"], x.get("hora"), x["away"]["nombre"], x["home"]["nombre"],
                "%.3f" % m["p_away"] if m else "-", "%.3f" % m["p_home"] if m else "-",
                ok, len(x.get("bloques") or {}), x.get("motivo") or ""))
    return d


# ------------------------------------------------------------------ F. snapshots y historial
def f_snap():
    titulo("F. SNAPSHOTS DE CUOTAS Y HISTORIAL DE PICKS")
    snaps = sorted(glob.glob(os.path.join(BASE, "salida", "odds_snapshots_*.csv")))
    if not snaps:
        p("Snapshots de cuotas: no hay archivos salida\\odds_snapshots_*.csv todavia (los crea cuotas.yml cada 3 horas)")
        alerta("AVISO", "no hay odds_snapshots todavia: el movimiento de linea y la linea de cierre dependen de ellos")
    for ruta in snaps:
        cols, rd = leer(ruta)
        n = 0; ts = []; juegos = set()
        for r in rd:
            n += 1; ts.append(r.get("ts_utc") or ""); juegos.add((r.get("liga"), r.get("game_id")))
        p("  %s: %d filas | %d partidos distintos | %s -> %s | %d fotos distintas" % (
            os.path.basename(ruta), n, len(juegos), min(ts) if ts else "-", max(ts) if ts else "-", len(set(ts))))
    ruta = os.path.join(BASE, "salida", "historial_picks.csv")
    p("")
    if not os.path.exists(ruta):
        p("historial_picks.csv: no existe"); return
    cols, rd = leer(ruta)
    filas = list(rd)
    p("historial_picks.csv: %d picks registrados" % len(filas))
    ids = collections.Counter((r["liga"], r["id"]) for r in filas)
    dup = [k for k, c in ids.items() if c > 1]
    if dup:
        alerta("FALLO", "historial_picks.csv tiene %d partidos repetidos" % len(dup))
    por = collections.Counter(r["liga"] for r in filas)
    p("  por liga: " + ", ".join("%s %d" % (a, b) for a, b in sorted(por.items())))
    pre = [r for r in filas if r["liga"] == "nhl" and r["fecha"] < "2026-10-07"]
    if pre:
        alerta("FALLO", "historial_picks.csv contiene %d juegos de NHL anteriores al 2026-10-07 (pretemporada)" % len(pre))
        p("  NHL antes del 2026-10-07 en el historial: %d" % len(pre))
    ya = [r for r in filas if r["fecha"] and r["fecha"] < HOY.isoformat()]
    p("  picks de dias anteriores (ya deberian poder calificarse con el resultado): %d" % len(ya))
    p("  nota: este archivo guarda el pick y la probabilidad; la calificacion contra el resultado real aun no esta automatizada.")


# ------------------------------------------------------------------ G. codigo
def g_codigo():
    titulo("G. CODIGO: se importa y compila todo")
    sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, "colectores"))
    mal = 0
    for sub in ("nucleo", "colectores", "utilidades"):
        for ruta in sorted(glob.glob(os.path.join(BASE, sub, "*.py"))):
            try:
                compile(open(ruta, encoding="utf-8").read(), ruta, "exec")
            except Exception as ex:
                mal += 1; p("  NO COMPILA %s: %s" % (os.path.relpath(ruta, BASE), str(ex)[:80]))
    for f in ("plataforma.py", "actualizar_todo.py"):
        ruta = os.path.join(BASE, f)
        if os.path.exists(ruta):
            try:
                compile(open(ruta, encoding="utf-8").read(), ruta, "exec")
            except Exception as ex:
                mal += 1; p("  NO COMPILA %s: %s" % (f, str(ex)[:80]))
    p("  archivos .py que no compilan: %d" % mal)
    if mal:
        alerta("FALLO", "%d archivos .py no compilan" % mal)
    for mod in ("nucleo.forma", "nucleo.jugadores", "nucleo.linea", "nucleo.equipos", "colectores.proximos_beisbol"):
        try:
            __import__(mod); p("  import %-30s ok" % mod)
        except Exception as ex:
            p("  import %-30s FALLA: %s" % (mod, str(ex)[:70])); alerta("FALLO", "no importa %s: %s" % (mod, str(ex)[:70]))
    # pruebas rapidas de ficha de tenis y de equipos
    try:
        from nucleo import forma
        ft = forma.forma_tenis()
        n = len(getattr(ft, "por_jugador", {}) or getattr(ft, "j", {}) or {})
        p("  forma de tenis cargada ok (%s jugadores indexados)" % (n or "?"))
    except Exception as ex:
        p("  forma de tenis FALLA: %s" % str(ex)[:80]); alerta("FALLO", "forma de tenis no carga: %s" % str(ex)[:80])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partidos", action="store_true", help="agrega una linea por partido")
    a = ap.parse_args()
    for fn, args in ((a_entorno, ()), (b_datos, ()), (c_jugadores, ()), (d_calib, ()), (e_pred, (a.partidos,)),
                     (f_snap, ()), (g_codigo, ())):
        try:
            fn(*args)
        except Exception as ex:                          # una seccion rota no tumba el informe
            titulo("ERROR EN %s" % fn.__name__); p(str(ex)); alerta("FALLO", "el diagnostico no pudo correr %s: %s" % (fn.__name__, str(ex)[:80]))
    cab = ["", "#" * 100, "RESUMEN: %d FALLO(S), %d AVISO(S)" % (sum(1 for n, _ in ALERTAS if n == "FALLO"), sum(1 for n, _ in ALERTAS if n == "AVISO")), "#" * 100]
    cab += ["  [%s] %s" % (n, t) for n, t in sorted(ALERTAS, key=lambda z: z[0] != "FALLO")] or ["  Todo en orden."]
    txt = "\n".join(["DIAGNOSTICO EDGELINE  %s" % dt.datetime.now().isoformat(timespec="seconds")] + cab + OUT)
    os.makedirs(os.path.join(BASE, "salida"), exist_ok=True)
    ruta = os.path.join(BASE, "salida", "diagnostico.txt")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(txt)
    with open(os.path.join(BASE, "salida", "diagnostico.json"), "w", encoding="utf-8") as fh:
        json.dump({"fecha": dt.datetime.now().isoformat(timespec="seconds"), "alertas": ALERTAS}, fh, ensure_ascii=False, indent=1)
    print(txt)
    print("\nInforme guardado en %s" % ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
