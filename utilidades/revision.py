# -*- coding: utf-8 -*-
"""
utilidades/revision.py - CHEQUEO DE INTEGRIDAD. Falla fuerte cuando algo no cuadra.

Por que existe: el 6-oct-2026 aparecieron siete defectos en una sola noche y NINGUNO aviso. Cada uno estuvo
dando cifras equivocadas durante dias con cara de correctas:
  1. nfl y nba se validaban mezcladas con NCAAF y NCAA basquet (faltaba la clave de liga en el validador):
     el total de NBA aparecia con +50.4% de skill y vale +0.4%.
  2. La copia local de datos tenia 689 juegos de KBO de los 4,377 reales: una medicion entera invalida.
  3. Sin "semillas.py mezclar" falta kbo_lanzadores.csv y el ganador de KBO cae de z 3.68 a 1.82.
  4. La subida a main fallaba callada y las predicciones no llegaban al repo.
  5. Los mercados mas fuertes (breaks de ATP) no tenian cuotas y por eso no generaban picks.
  6. El futbol europeo quedo atascado 16 dias sin que nada lo reportara.
  7. Un parche borro 124 lineas de otra sesion, entre ellas el bloqueo por descalibracion.
Este script existe para que eso no vuelva a pasar en silencio.

Codigos de salida: 0 todo bien o solo avisos; 1 hay ERRORES. En el workflow va SIN continue-on-error, para que
la corrida se ponga roja.

    python utilidades\\revision.py
    python utilidades\\revision.py --solo datos        (solo el bloque de datos)
    python utilidades\\revision.py --avisos-como-error (los WARN tambien fallan)
Solo stdlib.
"""
import argparse, csv, io, json, math, os, sys, datetime as dt
from collections import Counter, defaultdict

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Meses (inicio, fin) en que cada liga juega. Fuera de su temporada no se revisa el atraso.
# fin < inicio significa que cruza el anio (la NBA va de octubre a junio).
TEMPORADA = {
    "mlb": (3, 11), "npb": (3, 11), "kbo": (3, 11),
    "lmp": (10, 2), "lvbp": (10, 2), "lidom": (10, 2), "abl": (11, 2),
    "nhl": (10, 6), "nba": (10, 6), "ncaamb": (11, 4),
    "nfl": (9, 2), "ncaafb": (8, 1),
    "premier": (8, 5), "laliga": (8, 5), "seriea": (8, 5), "bundesliga": (8, 5),
    "ligue1": (8, 5), "ligamx": (7, 5), "mls": (2, 12), "champions": (9, 5),
}
# Dias de atraso tolerados dentro de temporada. Las ligas que juegan a diario toleran menos.
ATRASO = defaultdict(lambda: 10, {
    "mlb": 3, "npb": 3, "kbo": 3, "nhl": 3, "nba": 3, "ncaamb": 5,
    "nfl": 9, "ncaafb": 9,            # juegan una vez por semana
    # Ligas europeas: 25 dias. El paron internacional de septiembre de 2026 duro TRES SEMANAS (21-sep a 9-oct:
    # ultima jornada 19-20 de septiembre, vuelven el 10-11 de octubre) porque la final del Mundial fue el 19 de
    # julio y la FIFA paso de cinco ventanas a cuatro, con cuatro partidos por ventana. Con el tope de 9 dias,
    # el chequeo marcaba las cinco ligas como atrasadas el 6-oct-2026 cuando simplemente no habia partidos.
    # 25 = 19 dias de paron + unos dias de retraso de publicacion de football-data.co.uk.
    "premier": 25, "laliga": 25, "seriea": 25, "bundesliga": 25, "ligue1": 25,
    "ligamx": 12, "mls": 12,
    "champions": 25,                   # fase de liga cada 2-3 semanas, mas los parones
})
ARCHIVOS = {"beisbol.csv": ("mlb", "npb", "kbo", "lmp", "lvbp", "lidom", "abl"),
            "nba.csv": ("nba", "ncaamb"), "americano.csv": ("nfl", "ncaafb"),
            "hockey.csv": ("nhl",),
            "futbol.csv": ("premier", "laliga", "seriea", "bundesliga", "ligue1", "ligamx", "mls", "champions")}
# Rango plausible del MAE de la linea base del total, por liga. Fuera de esto la base esta mezclada o rota.
# (el defecto 1 se delataba con un MAE base de 29.3 en NBA, imposible para una liga sola)
MAE_BASE = {"beisbol_mlb": (3.0, 5.0), "beisbol_npb": (2.5, 4.5), "beisbol_kbo": (3.0, 5.5),
            "beisbol_lmp": (2.5, 4.5), "nba": (14.0, 22.0), "ncaamb": (12.0, 20.0),
            "nfl": (9.0, 15.0), "ncaafb": (11.0, 18.0), "hockey": (1.5, 3.0)}
# Juegos que debe tener cada liga como piso (defecto 2: la copia local tenia 689 de KBO de 4,377).
PISO_JUEGOS = {"mlb": 9000, "npb": 4000, "kbo": 4000, "nhl": 4000, "nba": 5000, "ncaamb": 18000,
               "nfl": 1400, "ncaafb": 4000, "lmp": 1700, "lvbp": 1200, "lidom": 800, "abl": 600,
               "premier": 1900, "laliga": 1900, "seriea": 1900, "bundesliga": 1500, "ligue1": 1700,
               "ligamx": 1900, "mls": 2900}
INVENTARIO = os.path.join(REPO, "salida", "inventario_datos.json")

ERR, WARN = [], []


def err(bloque, msg):
    ERR.append((bloque, msg)); print("  ERROR  [%s] %s" % (bloque, msg))


def warn(bloque, msg):
    WARN.append((bloque, msg)); print("  aviso  [%s] %s" % (bloque, msg))


def ok(bloque, msg):
    print("  ok     [%s] %s" % (bloque, msg))


def _hoy():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=-6)).date()


def _en_temporada(liga, hoy):
    r = TEMPORADA.get(liga)
    if not r:
        return True
    ini, fin = r
    m = hoy.month
    return (ini <= m <= fin) if ini <= fin else (m >= ini or m <= fin)


def _inicio_temporada(liga, hoy):
    """Fecha en que se abrio la ventana de temporada vigente. None si la liga no tiene ventana."""
    r = TEMPORADA.get(liga)
    if not r:
        return None
    ini = r[0]
    return dt.date(hoy.year if hoy.month >= ini else hoy.year - 1, ini, 1)


DIAS_ARRANQUE = 45   # margen desde que abre la ventana: muchas ligas empiezan a jugar semanas despues


def _cargar(nombre):
    try:
        with io.open(os.path.join(BASE, "salida", nombre), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ----------------------------------------------------------------------------- 1. DATOS
def revisar_datos():
    print("\n1. DATOS: conteo por liga, atraso dentro de temporada y caidas respecto a la corrida anterior")
    hoy = _hoy()
    prev = {}
    if os.path.exists(INVENTARIO):
        try:
            with io.open(INVENTARIO, encoding="utf-8") as f:
                prev = (json.load(f) or {}).get("ligas") or {}
        except Exception:
            prev = {}
    actual = {}
    for arch, ligas in ARCHIVOS.items():
        ruta = os.path.join(BASE, "datos", arch)
        if not os.path.exists(ruta):
            err("datos", "falta %s" % arch); continue
        n = Counter(); ult = defaultdict(str); vistos = set()
        with io.open(ruta, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                lg = (r.get("league") or "").lower()
                pk = str(r.get("gamePk") or r.get("game_id") or r.get("id") or "")
                k = (lg, pk)
                if k in vistos:
                    continue
                vistos.add(k); n[lg] += 1
                d = (r.get("game_date") or "")[:10]
                if d > ult[lg]:
                    ult[lg] = d
        for lg in ligas:
            c = n.get(lg, 0)
            actual[lg] = {"juegos": c, "ultimo": ult.get(lg, "")}
            if c == 0:
                warn("datos", "%s: sin ningun juego en %s" % (lg.upper(), arch)); continue
            piso = PISO_JUEGOS.get(lg)
            if piso and c < piso:
                err("datos", "%s: %d juegos, por debajo del piso de %d (datos incompletos)" % (lg.upper(), c, piso))
            antes = (prev.get(lg) or {}).get("juegos")
            if antes and c < antes * 0.98:
                err("datos", "%s: bajo de %d a %d juegos respecto a la corrida anterior" % (lg.upper(), antes, c))
            u = ult.get(lg) or ""
            if u and _en_temporada(lg, hoy):
                try:
                    fu = dt.date.fromisoformat(u)
                except ValueError:
                    fu = None
                ini = _inicio_temporada(lg, hoy)
                if fu is not None:
                    if ini and fu < ini:
                        # no hay NINGUN juego de la temporada vigente: normal si acaba de abrir la ventana
                        # (la NBA abre en octubre y arranca el 21; las invernales abren en octubre y empiezan
                        # a mediados de mes), y problema si ya paso mas de mes y medio.
                        d_ini = (hoy - ini).days
                        if d_ini > DIAS_ARRANQUE:
                            err("datos", "%s: ningun juego de la temporada que abrio el %s (hace %d dias); "
                                         "el ultimo es del %s. El colector de esa liga no esta trayendo nada." % (
                                             lg.upper(), ini.isoformat(), d_ini, u))
                        else:
                            ok("datos", "%s: temporada recien abierta (%s), aun sin juegos. Normal." % (lg.upper(), ini.isoformat()))
                    else:
                        dias = (hoy - fu).days
                        if dias > ATRASO[lg]:
                            err("datos", "%s esta jugando y su ultimo juego es del %s (%d dias de atraso, tope %d)" % (
                                lg.upper(), u, dias, ATRASO[lg]))
    if not ERR:
        ok("datos", "%d ligas con conteo y frescura dentro de lo esperado" % len(actual))
    else:
        print("         Para refrescar datos/ desde la rama 'datos':")
        print("           Windows:  git fetch origin datos")
        print("                     git archive --format=zip --output=\"$env:TEMP\\datos.zip\" FETCH_HEAD datos")
        print("                     Expand-Archive -Path \"$env:TEMP\\datos.zip\" -DestinationPath . -Force")
        print("                     python utilidades\\semillas.py mezclar")
        print("           Linux:    git fetch origin datos && git archive FETCH_HEAD datos | tar -x && "
              "python utilidades/semillas.py mezclar")
        print("         (el tar.exe de Windows no lee bien la tuberia de git archive: usa el zip)")
    try:
        os.makedirs(os.path.dirname(INVENTARIO), exist_ok=True)
        with io.open(INVENTARIO, "w", encoding="utf-8") as f:
            json.dump({"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "ligas": actual}, f, ensure_ascii=False, indent=1)
    except Exception as e:
        warn("datos", "no se pudo escribir el inventario (%s)" % str(e)[:60])


# ----------------------------------------------------------------------------- 2. CAPAS CON ARCHIVO PROPIO
def revisar_capas():
    print("\n2. CAPAS: que las ligas con capa de abridores tengan su archivo de lanzadores")
    sys.path.insert(0, REPO)
    try:
        from nucleo import abridores as AB
    except Exception as e:
        warn("capas", "no se pudo importar nucleo.abridores (%s)" % str(e)[:60]); return
    for lg in ("kbo", "npb", "lmp"):
        try:
            aplica = AB.aplica(lg)
        except Exception:
            aplica = False
        if not aplica:
            continue
        filas = len(AB._filas(BASE, lg))
        if filas == 0:
            err("capas", "%s aplica la capa de abridores y su archivo esta vacio o no existe (%s). "
                         "Falta correr: python utilidades/semillas.py mezclar" % (lg.upper(), AB._ruta(BASE, lg)))
        else:
            ok("capas", "%s: %d filas de lanzadores" % (lg.upper(), filas))


# ----------------------------------------------------------------------------- 3. VALIDACION COHERENTE
def revisar_validacion():
    print("\n3. VALIDACION: que el n no supere los partidos de la liga y que el MAE base sea plausible")
    vm = _cargar("validacion_mercados.json")
    if not vm:
        warn("validacion", "no existe salida/validacion_mercados.json"); return
    inv = {}
    if os.path.exists(INVENTARIO):
        try:
            with io.open(INVENTARIO, encoding="utf-8") as f:
                inv = (json.load(f) or {}).get("ligas") or {}
        except Exception:
            inv = {}
    liga_de = {"beisbol_mlb": "mlb", "beisbol_npb": "npb", "beisbol_kbo": "kbo", "beisbol_lmp": "lmp",
               "hockey": "nhl", "nba": "nba", "ncaamb": "ncaamb", "nfl": "nfl", "ncaafb": "ncaafb"}
    for dep, mk in (vm.get("deportes") or {}).items():
        lg = liga_de.get(dep)
        tot = (inv.get(lg) or {}).get("juegos") if lg else None
        g = mk.get("Ganador") or {}
        n = g.get("n")
        if tot and n and n > tot:
            err("validacion", "%s: el Ganador se midio con n=%d y la liga solo tiene %d juegos. Dos causas posibles: "
                              "(a) el validador esta mezclando dos ligas del mismo archivo porque le falta la clave "
                              "'liga' en CFG, o (b) datos/ esta incompleto y la validacion es de otra corrida con mas "
                              "datos. Revisa primero los errores del bloque 1." % (dep, n, tot))
        elif tot and n:
            ok("validacion", "%s: n=%d de %d juegos de la liga" % (dep, n, tot))
        rango = MAE_BASE.get(dep)
        te = mk.get("Total esperado") or {}
        base = te.get("base")
        if rango and base is not None and not (rango[0] <= base <= rango[1]):
            err("validacion", "%s: el MAE base del total es %.2f, fuera del rango plausible %.1f-%.1f. "
                              "Base mezclada o rota: el skill de ese mercado no es comparable." % (dep, base, rango[0], rango[1]))


# ----------------------------------------------------------------------------- 4. COBERTURA DE CUOTAS
def revisar_cuotas():
    print("\n4. CUOTAS: que los mercados publicables tengan precio en los partidos del dia")
    prx = _cargar("proximos.json")
    if not prx:
        warn("cuotas", "no existe salida/proximos.json"); return
    hoy = _hoy().isoformat()
    man = (_hoy() + dt.timedelta(days=1)).isoformat()
    por = defaultdict(lambda: [0, 0])
    for p in prx.get("partidos") or []:
        if p.get("fecha") not in (hoy, man):
            continue
        val = p.get("validacion") or {}
        if val.get("Ganador") != "publicable":
            continue
        q = p.get("cuotas") or {}
        a = por[p.get("liga")]
        a[0] += 1
        if q.get("ml_home") is not None and q.get("ml_away") is not None:
            a[1] += 1
    if not por:
        warn("cuotas", "ningun partido de hoy o manana con el ganador publicable"); return
    for lg, (n, con) in sorted(por.items()):
        pct = 100.0 * con / n
        if n >= 4 and pct < 50.0:
            err("cuotas", "%s: el ganador es publicable y solo %d de %d partidos (%.0f%%) tienen cuota. "
                          "Sin precio no hay pick." % (lg.upper(), con, n, pct))
        elif pct < 80.0:
            warn("cuotas", "%s: %d de %d partidos con cuota (%.0f%%)" % (lg.upper(), con, n, pct))
        else:
            ok("cuotas", "%s: %d de %d con cuota" % (lg.upper(), con, n))


# ----------------------------------------------------------------------------- 5. FRESCURA DE LA SALIDA
def revisar_frescura(horas=14):
    print("\n5. SALIDA: que las predicciones publicadas no esten viejas")
    prx = _cargar("proximos.json")
    if not prx:
        warn("salida", "no existe salida/proximos.json"); return
    gen = (prx.get("generado") or "")[:19]
    try:
        t = dt.datetime.fromisoformat(gen)
    except ValueError:
        warn("salida", "no se pudo leer 'generado' de proximos.json (%r)" % gen); return
    # 'generado' se escribe con la hora local de quien corre: UTC en el runner de Actions, UTC-6 en tu PC.
    # Se prueban las dos lecturas y se toma la que de una edad no negativa.
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cand = [(utc - t).total_seconds() / 3600.0, (utc + dt.timedelta(hours=-6) - t).total_seconds() / 3600.0]
    pos = [x for x in cand if x >= -0.5]
    if not pos:
        warn("salida", "proximos.json dice que se genero en el futuro bajo cualquier zona horaria (%s)" % gen); return
    edad = min(pos)
    if edad > horas:
        err("salida", "proximos.json se genero hace %.1f h (tope %d h). La subida a main pudo estar fallando." % (edad, horas))
    else:
        ok("salida", "proximos.json tiene %.1f h" % edad)


# ----------------------------------------------------------------------------- 6. CALIBRACION EN VIVO
def revisar_calibracion(min_n=30, brecha=0.10):
    print("\n6. CALIBRACION EN VIVO: mercados que prometen mas de lo que aciertan")
    ruta = os.path.join(BASE, "salida", "historial_predicciones_calificado.csv")
    if not os.path.exists(ruta):
        warn("calibracion", "no existe historial_predicciones_calificado.csv"); return
    acum = defaultdict(lambda: [0, 0, 0.0])
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("estado") != "calificado":
                continue
            m = (r.get("mercado") or "").split()[0]
            if m not in ("Ganador", "Total", "Games"):
                continue
            try:
                p = float(r["p_modelo"])
            except (TypeError, ValueError, KeyError):
                continue
            a = acum[(r.get("liga"), "Total" if m in ("Total", "Games") else "Ganador")]
            a[0] += 1
            a[1] += 1 if r.get("acierto") in ("1", "True", "si", "sí") else 0
            a[2] += p
    malos = 0
    for (lg, mk), (n, ac, sp) in sorted(acum.items()):
        if n < min_n:
            continue
        pm = sp / n; tasa = ac / n
        se = math.sqrt(max(pm * (1 - pm), 1e-9) / n)
        z = (tasa - pm) / se
        if (pm - tasa) >= brecha and z <= -2.0:
            err("calibracion", "%s %s: prometio %.1f%% y acerto %.1f%% en %d casos (z %.2f). "
                               "Ese mercado no se debe apostar hasta corregirlo." % (lg.upper(), mk, 100 * pm, 100 * tasa, n, z))
            malos += 1
    if not malos:
        ok("calibracion", "%d combinaciones liga-mercado revisadas, ninguna descalibrada con n>=%d" % (len(acum), min_n))


# ----------------------------------------------------------------------------- 7. ARCHIVOS SIN PUBLICAR
def revisar_git():
    print("\n7. GIT: archivos rastreados modificados que no se van a publicar")
    import subprocess
    try:
        r = subprocess.run(["git", "-C", REPO, "status", "--porcelain"], capture_output=True, text=True, timeout=60)
    except Exception as e:
        warn("git", "no se pudo correr git status (%s)" % str(e)[:60]); return
    mod = [l[3:].strip() for l in (r.stdout or "").splitlines() if l[:2].strip() in ("M", "MM", "AM")]
    sal = [m for m in mod if m.startswith("salida/")]
    if sal:
        warn("git", "%d archivos de salida/ modificados: %s. Verifica que esten en la lista de "
                    "publicacion de los workflows." % (len(sal), ", ".join(sal[:6])))
    else:
        ok("git", "sin archivos de salida/ modificados fuera de lo publicado")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="", help="datos,capas,validacion,cuotas,salida,calibracion,git")
    ap.add_argument("--avisos-como-error", action="store_true")
    a = ap.parse_args()
    pedidos = {x.strip() for x in a.solo.split(",") if x.strip()}
    print("REVISION DE INTEGRIDAD  %s  (base %s)" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), BASE))
    bloques = [("datos", revisar_datos), ("capas", revisar_capas), ("validacion", revisar_validacion),
               ("cuotas", revisar_cuotas), ("salida", revisar_frescura), ("calibracion", revisar_calibracion),
               ("git", revisar_git)]
    for nombre, fn in bloques:
        if pedidos and nombre not in pedidos:
            continue
        try:
            fn()
        except Exception as e:
            warn(nombre, "el bloque fallo (%s: %s)" % (type(e).__name__, str(e)[:80]))
    print("\n" + "=" * 70)
    print("RESULTADO: %d errores, %d avisos" % (len(ERR), len(WARN)))
    for b, m in ERR:
        print("  ERROR  [%s] %s" % (b, m))
    if ERR:
        print("\nLa corrida se marca en rojo a proposito: hay algo que esta dando numeros equivocados.")
    return 1 if (ERR or (a.avisos_como_error and WARN)) else 0


if __name__ == "__main__":
    sys.exit(main())
