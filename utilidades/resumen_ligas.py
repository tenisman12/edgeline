# -*- coding: utf-8 -*-
"""
utilidades/resumen_ligas.py - un archivo chico por liga con TODO lo que se usa para decidir -> salida/resumen/<liga>.json

Por que: salida/proximos.json trae todos los deportes (~9 MB) y ningun asistente (Gemini, ChatGPT, Claude) lo lee
completo desde un enlace. Este script lo parte por liga, deja solo los partidos de hoy y manana (CDMX), quita lo que no
sirve para decidir (logos, puntajes internos del Pick Premium) y le pega al partido las decisiones del sistema
(decidir.json, picks_del_dia.json) y el movimiento de mercado/publico (mercado_publico.json). Resultado: 50-600 KB por
liga, legible entero con el enlace raw:

    https://raw.githubusercontent.com/tenisman12/edgeline/main/salida/resumen/nhl.json
    https://raw.githubusercontent.com/tenisman12/edgeline/main/salida/resumen/atp.json
    https://raw.githubusercontent.com/tenisman12/edgeline/main/salida/resumen/indice.json   (que ligas hay, cuantos partidos, tamano)

Ademas escribe salida/resumen/LEEME.md con la explicacion de cada campo y las reglas de decision, para que quien lo lea
(persona o IA) sepa como usarlo.

    python utilidades\\resumen_ligas.py            (hoy y manana)
    python utilidades\\resumen_ligas.py --dias 3
"""
import os, sys, json, argparse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import io

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(REPO, "salida") if os.path.exists(os.path.join(REPO, "salida", "proximos.json")) else io.ruta("salida")
DESTINO = os.path.join(SALIDA, "resumen")
QUITAR_PARTIDO = ("picks",)                 # puntajes internos del Pick Premium: ruido para un lector externo
QUITAR_EQUIPO = ("logo",)
TZ = -6
LIMITE_KB = 600          # por encima de esto se escribe tambien un archivo por dia


def _cargar(nombre):
    r = os.path.join(SALIDA, nombre)
    if not os.path.exists(r):
        return None
    with open(r, encoding="utf-8") as f:
        return json.load(f)


def _limpiar(p):
    q = {k: v for k, v in p.items() if k not in QUITAR_PARTIDO}
    if p.get("tipo") == "tenis":
        q.pop("estadisticas_equipo", None)      # en tenis repite forma.detalle* (L5/L10/12m/superficie/formato)
    for lado in ("home", "away"):
        if isinstance(q.get(lado), dict):
            q[lado] = {k: v for k, v in q[lado].items() if k not in QUITAR_EQUIPO}
    return q


def _indexar(lista, claves=("liga", "id")):
    out = {}
    for x in lista or []:
        k = tuple(str(x.get(c)) for c in claves)
        out.setdefault(k, []).append(x)
    return out


def _norm(s):
    return io.norm(s or "")


def construir(dias=2):
    prox = _cargar("proximos.json")
    if not prox:
        print("No existe salida/proximos.json"); return {}
    hoy = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ)).date()
    fechas = {(hoy + dt.timedelta(days=i)).isoformat() for i in range(dias)}
    dec = _indexar((_cargar("decidir.json") or {}).get("partidos"))
    pdd = _cargar("picks_del_dia.json") or {}
    picks_of = _indexar(pdd.get("picks"))
    cand = _indexar(pdd.get("candidatos_fuera"))
    pdd_part = _indexar(pdd.get("partidos"))
    pub = {}
    for m in (_cargar("mercado_publico.json") or {}).get("partidos") or []:
        pub.setdefault(m.get("liga"), []).append(m)
    val = _cargar("validacion_mercados.json")
    track = _cargar("track_record.json") or {}
    por_liga = {}
    for p in prox.get("partidos", []):
        if p.get("fecha") not in fechas:
            continue
        q = _limpiar(p)
        k = (str(p.get("liga")), str(p.get("id")))
        if k in dec: q["sistema_estimado"] = dec[k][0]
        if k in picks_of: q["pick_oficial"] = picks_of[k]
        if k in cand: q["candidato_fuera"] = cand[k]
        if k in pdd_part: q["decision_picks_dia"] = pdd_part[k][0]
        # movimiento sharp/publico: por nombre de partido "away @ home"
        h, a = _norm(p["home"].get("nombre")), _norm(p["away"].get("nombre"))
        for m in pub.get(p.get("liga"), []):
            t = _norm(m.get("partido"))
            if h and a and h in t and a in t:
                q["mercado_publico"] = m; break
        por_liga.setdefault(p["liga"], []).append(q)
    os.makedirs(DESTINO, exist_ok=True)
    for viejo in os.listdir(DESTINO):                   # no dejar ligas o dias que ya no aplican
        if viejo.endswith(".json"):
            os.remove(os.path.join(DESTINO, viejo))
    gen = prox.get("generado")
    indice = {"generado": gen, "escrito": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "fechas": sorted(fechas),
              "tz": "America/Mexico_City", "ligas": {}, "como_leer": "salida/resumen/LEEME.md",
              "base_raw": "https://raw.githubusercontent.com/tenisman12/edgeline/main/salida/resumen/"}
    for liga, ps in sorted(por_liga.items()):
        ps.sort(key=lambda x: (x.get("fecha", ""), x.get("hora", "")))
        rec = {"liga": liga, "generado": gen, "fechas": sorted(fechas), "partidos": len(ps),
               "con_modelo": sum(1 for x in ps if x.get("modelo")),
               "validacion_modelo": (val or {}).get(liga) if isinstance(val, dict) else None,
               "track_record_modelo": {k: v for k, v in (track.get("predicciones_modelo", {}).get("por_liga_mercado") or {}).items() if k.startswith(liga + "|")},
               "track_record_picks": (track.get("por_liga") or {}).get(liga),
               "partidos_lista": ps}
        ruta = os.path.join(DESTINO, "%s.json" % liga)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
        ent = {"partidos": len(ps), "con_modelo": rec["con_modelo"], "kb": round(os.path.getsize(ruta) / 1024), "archivo": "%s.json" % liga}
        if ent["kb"] > LIMITE_KB:                       # tenis: ademas un archivo por dia, mas chico
            ent["por_dia"] = {}
            for fch in sorted(fechas):
                sub = [x for x in ps if x.get("fecha") == fch]
                if not sub: continue
                r2 = dict(rec, fechas=[fch], partidos=len(sub), con_modelo=sum(1 for x in sub if x.get("modelo")), partidos_lista=sub)
                ruta2 = os.path.join(DESTINO, "%s_%s.json" % (liga, fch))
                with open(ruta2, "w", encoding="utf-8") as f:
                    json.dump(r2, f, ensure_ascii=False, separators=(",", ":"))
                ent["por_dia"][fch] = {"archivo": os.path.basename(ruta2), "partidos": len(sub), "kb": round(os.path.getsize(ruta2) / 1024)}
        indice["ligas"][liga] = ent
    with open(os.path.join(DESTINO, "indice.json"), "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DESTINO, "LEEME.md"), "w", encoding="utf-8") as f:
        f.write(LEEME)
    for liga, d in indice["ligas"].items():
        print("  %-10s %3d partidos (%d con modelo) %5d KB" % (liga, d["partidos"], d["con_modelo"], d["kb"]))
    print("Escrito %s (%d ligas)" % (DESTINO, len(indice["ligas"])))
    return indice


LEEME = """# Resumen por liga (salida/resumen/)

Un archivo por liga con los partidos de hoy y manana (hora CDMX) y todo lo que Edgeline usa para decidir.
Lo genera el bot tres veces al dia. Enlaces (texto plano, se abren sin cuenta):

- indice.json: que ligas hay, cuantos partidos y el tamano de cada archivo.
- <liga>.json: nhl, nfl, mlb, kbo, npb, nba, ncaafb, atp, wta, mls, premier, laliga, seriea, bundesliga, ligue1, ligamx.
  Ejemplo: https://raw.githubusercontent.com/tenisman12/edgeline/main/salida/resumen/nhl.json
- Tenis (atp, wta) trae muchos partidos; ademas del archivo completo hay uno por dia, mas chico:
  atp_2026-10-05.json, wta_2026-10-05.json (el indice dice cuales existen). Usa el del dia que te interesa.

## Campos de cada partido (partidos_lista)
- liga, fecha, hora (CDMX), estado, estadio, torneo/ronda/superficie (tenis), serie y nota (playoffs).
- home / away: nombre, abreviatura, record, abridor probable (probable) o ranking (tenis).
- modelo: p_home / p_away (probabilidad de ganar), x_home / x_away (marcador esperado por equipo), total esperado,
  linea_total y p_over, spread calculado, confianza. Hockey: porteros (titular y sv%), descanso (back-to-back),
  xg_nhl (xG a favor/en contra por 60, xG%, Corsi, suerte). Beisbol: abridores con avanzadas (FIP temporada y
  ultimas 5, K%, BB%, HR/9, WHIP, IP por salida, bullpen_game). Tenis: extra con breaks esperados, probabilidad
  de al menos un break y holds de saque.
- cuotas: casa con mejor precio, moneyline (formato americano), total y spread con sus cuotas, y los de apertura.
- mercados: por lado, cuota, p_modelo, p_mercado (lo que implica la cuota), edge, estado de validacion.
- validacion: si el modelo de ese mercado esta "publicable" (demostrado en esa liga) o "sin_validar".
- forma: osciladores basicos, osciladores_detalle (forma 3/5, ataque/defensa recientes, dif10, dif3, volatilidad,
  forma local/visita, momentum de ELO, over/under reciente, carga: juegos en 7 dias, descanso, back-to-back),
  osciladores_tecnicos (RSI 5/10/15 del margen, MACD, MACD del ELO, Bollinger, estocastico, ROC del ELO,
  pitagorico y residuo) y stats con osc_L10 por estadistica.
- estadisticas_equipo: temporada y ventanas L5/L10 con sus osciladores. jugadores_clave: porteros/abridores con
  ventana de 10 juegos. h2h_datos: enfrentamientos previos. contexto: lesiones.
- movimiento: apertura vs actual del moneyline y total. mercado_publico: probabilidad sharp (Pinnacle) y del
  publico, apertura y actual, movimiento en puntos (mov_sharp_pp > 0 = la linea se movio a favor de ese lado).
- sistema_estimado (beisbol): p_modelo, p_sharp, p_final, detalle del modelo (ELO, diferencial, abridores).
- decision_picks_dia / pick_oficial / candidato_fuera: lo que decidio el sistema para ese partido, con EV,
  confianza, stake y razon.
- Cabecera del archivo: validacion_modelo (por mercado), track_record_modelo (acierto, Brier, MAE por mercado)
  y track_record_picks (como le ha ido a los picks de esa liga).

## Reglas de decision que sigue Edgeline (aplicarlas igual)
- El modelo siempre vota. Mezcla con el mercado en logit: p_final = inv(logit(p_mercado) + w*(logit(p_modelo) - logit(p_mercado))),
  con w = 0.5 en NHL (ganador y total), 0.5 en NFL (restando 3.4 puntos al over), 0.25 en beisbol.
  p_mercado = Pinnacle si hay; si no (KBO, NPB), consenso de casas.
- EV = p_final * cuota decimal - 1. Confianza: alta >= 8%, media 4-8%, baja 1-4%, minima < 1%. Unidades 3 / 2 / 1 / 0.
- Cuota minima 1.70, sin cuota maxima. Solo ganador y totales; spread, run line y puck line no se apuestan.
- Brecha modelo-mercado >= 10 puntos a favor del pick: bajar a minima y revisar; >= 15: buscar la causa antes de decidir.
- Capas medidas: ELO y diferencial de temporada predicen; en beisbol los osciladores basicos, L10, L5, H2H,
  local/visita y descanso pesan cero. En hockey el back-to-back pesa (44% vs 51% descansado). Rachas de 3+
  derrotas: +2-3 puntos; 3+ victorias: -1-2 puntos. El movimiento de linea es informacion, no ventaja.
- Tenis breaks: al valor del modelo restar 0.3 (sesgo medido); pick solo si la linea de la casa esta a >= 1 break,
  cuota >= 1.70, 1 unidad. Error tipico 1.65 breaks.
- Formato del analisis por partido: contexto; modelo (siempre marcador esperado por equipo, ganador, probabilidad,
  total); abridores o porteros con avanzadas; todos los osciladores; mercado y publico; dudas medidas; decision con
  p_final, EV, cuota minima, confianza, unidades, conteo a favor/en contra, por que si / por que no, y siempre un
  lado del total. Neutro y objetivo; listas, no tablas. No inventar: si falta un dato, "sin dato".
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=2)
    a = ap.parse_args()
    construir(a.dias)
    return 0


if __name__ == "__main__":
    sys.exit(main())
