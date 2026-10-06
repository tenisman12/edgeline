# Resumen por liga (salida/resumen/)

Un archivo por liga con los partidos de hoy y manana (hora CDMX) y todo lo que Edgeline usa para decidir.
Lo genera el bot tres veces al dia. Enlaces (texto plano, se abren sin cuenta):

- indice.json: que ligas hay, cuantos partidos y el tamano de cada archivo.
- <liga>.json: nhl, nfl, mlb, kbo, npb, nba, ncaafb, atp, wta, mls, premier, laliga, seriea, bundesliga, ligue1, ligamx.
  Ejemplo: https://raw.githubusercontent.com/tenisman12/edgeline/main/salida/resumen/nhl.json
- Tenis (atp, wta) trae muchos partidos; ademas del archivo completo hay uno por dia, mas chico:
  atp_2026-10-05.json, wta_2026-10-05.json (el indice dice cuales existen). Usa el del dia que te interesa.

## Campos de cada partido (partidos_lista)
- liga, fecha, hora (CDMX), estado, estadio, torneo/ronda/superficie (tenis), serie y nota (playoffs).
- clima (al aire libre, Open-Meteo a la hora del juego): temp_c, humedad, prob_lluvia, lluvia_mm, viento_kmh,
  rafagas_kmh, dir_viento y alertas (lluvia probable, viento fuerte, frio, calor); bajo techo: techado = true.
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
