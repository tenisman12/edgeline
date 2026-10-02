# -*- coding: utf-8 -*-
"""
utilidades/limpiar_historial.py - deja en salida\\historial_picks.csv solo lo que debe contar en el track record.

  QUITA (no deberian estar):
    - PRETEMPORADA que se colo (PRE_INICIO por liga)
    - FORMATO VIEJO (sin nivel Pick Premium) en ligas que entonces no estaban validadas (FORMATO_VIEJO)
  ANULA (se quedan a la vista, con el motivo en la columna 'anulado'; calificar_picks.py no los cuenta):
    - Picks REGISTRADOS DESPUES DEL INICIO del partido: la cuota ya era en vivo. El inicio sale de la columna
      inicio_utc (registros nuevos) o del commence_time de salida/cuotas_sharp_*.csv y odds_snapshots_*.csv.
      'registrado' sin zona horaria se toma como UTC (hora de GitHub Actions).
    - Lista manual ANULAR_MANUAL (liga, id, motivo) para casos revisados a mano.

Es idempotente: el bot lo corre en cada corrida antes de calificar.
Guarda una copia en salida\\historial_picks.respaldo.csv antes de cambiar nada.

    python utilidades\\limpiar_historial.py            (solo muestra que haria)
    python utilidades\\limpiar_historial.py --aplicar  (aplica y guarda)
"""
import argparse, csv, datetime as dt, glob, os, shutil, sys

BASE = os.path.abspath(os.environ.get("EDGELINE_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
PRE_INICIO = {"nhl": "2026-09-29"}
FORMATO_VIEJO = {"ncaafb"}        # picks registrados antes del Pick Premium (columna nivel vacia) en estas ligas
ANULAR_MANUAL = {}                 # {("liga", "id"): "motivo"}


def _utc(s):
    """'2026-10-02T11:10:52', '...Z' o '...+00:00' -> datetime UTC. None si no se puede."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        if len(s2) == 16:                       # AAAA-MM-DDTHH:MM
            s2 += ":00"
        t = dt.datetime.fromisoformat(s2)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _inicios():
    """{liga: {(home, away): {inicio UTC, ...}}} desde las fotos de cuotas."""
    try:
        from nucleo import sharp
    except Exception:
        return {}, None
    out = {}
    archivos = glob.glob(os.path.join(BASE, "salida", "cuotas_sharp_*.csv")) + glob.glob(os.path.join(BASE, "salida", "odds_snapshots_*.csv"))
    for ruta in archivos:
        try:
            with open(ruta, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    lg = sharp.liga_de(r.get("sport") or "") if r.get("sport") else (r.get("liga") or "")
                    ini = _utc(r.get("commence_time") or r.get("fecha_utc"))
                    if not lg or not ini:
                        continue
                    out.setdefault(lg, {}).setdefault((r.get("home") or "", r.get("away") or ""), set()).add(ini)
        except Exception:
            continue
    return out, sharp


def _inicio_de(r, inicios, sharp):
    ini = _utc(r.get("inicio_utc"))
    if ini or not sharp:
        return ini
    try:
        f = dt.date.fromisoformat(r["fecha"][:10])
    except ValueError:
        return None
    cand = []
    for (h, a), ts in (inicios.get(r["liga"]) or {}).items():
        # mismo partido: los dos equipos se parecen (nombres cortos de la ficha contra nombres largos de la casa)
        ok = (sharp._parecido(h, r["home"]) >= 0.99 and sharp._parecido(a, r["away"]) >= 0.99) or \
             (sharp._parecido(h, r["away"]) >= 0.99 and sharp._parecido(a, r["home"]) >= 0.99)
        if ok:
            cand += [t for t in ts if abs((t.date() - f).days) <= 1]
    if not cand:
        return None
    # el inicio cuya fecha en CDMX (UTC-6) coincide con la del partido
    return min(cand, key=lambda t: abs(((t - dt.timedelta(hours=6)).date() - f).days))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    ruta = os.path.join(BASE, "salida", "historial_picks.csv")
    if not os.path.exists(ruta):
        print("No existe %s" % ruta); return 1
    with open(ruta, encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh); cols = list(rd.fieldnames); filas = list(rd)
    faltan_cols = [c for c in ("inicio_utc", "anulado") if c not in cols]
    cols += faltan_cols
    quitar = [r for r in filas if (PRE_INICIO.get(r["liga"]) and r["fecha"] < PRE_INICIO[r["liga"]])
              or (r["liga"] in FORMATO_VIEJO and not (r.get("nivel") or "").strip())]
    quedan = [r for r in filas if r not in quitar]
    inicios, sharp = _inicios()
    anular = []
    for r in quedan:
        if (r.get("anulado") or "").strip():
            continue
        motivo = ANULAR_MANUAL.get((r["liga"], r["id"]))
        if not motivo:
            reg, ini = _utc(r.get("registrado")), _inicio_de(r, inicios, sharp)
            if reg and ini and reg >= ini:
                motivo = "registrado despues del inicio (%s, inicio %s UTC)" % (reg.strftime("%Y-%m-%d %H:%M"), ini.strftime("%Y-%m-%d %H:%M"))
        if motivo:
            r["anulado"] = motivo; anular.append(r)
    print("Picks en el historial: %d | a quitar (pretemporada / formato viejo): %d | a anular: %d | quedarian: %d" % (
        len(filas), len(quitar), len(anular), len(quedan)))
    for r in quitar:
        print("  quitar: %s %s %s @ %s (%s)" % (r["liga"], r["fecha"], r["away"], r["home"], r["pick"]))
    for r in anular:
        print("  anular: %s %s %s @ %s | %s %s | %s" % (r["liga"], r["fecha"], r["away"], r["home"], r.get("nivel") or "-", r["pick"], r["anulado"]))
    if a.aplicar and (quitar or anular or faltan_cols):
        shutil.copy2(ruta, os.path.join(BASE, "salida", "historial_picks.respaldo.csv"))
        with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader()
            for r in quedan:
                for c in cols:
                    r.setdefault(c, "")
                w.writerow(r)
        print("Listo. Copia anterior en salida\\historial_picks.respaldo.csv")
    elif quitar or anular:
        print("Para aplicar: python utilidades\\limpiar_historial.py --aplicar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
