# Hipótesis (escrita antes de ver resultados) — 2026-10-09

Capa de decisión para apostar a cuota de 1.80 o más. Script: `utilidades/minar_cuotas_altas.py`.

Objetivo de Alejandro: ganar a cuotas decentes (1.80 o más, promedio cerca de 2), sin depender de la brecha contra Pinnacle.
La brecha se reporta como columna, no como filtro.

- Datos: fútbol (7 ligas; probabilidad del modelo as-of por bloques de 30 días; mejor precio entre casas y cierre de Pinnacle)
  y NFL (probabilidad as-of de `entrenar`; cierre de una casa de `mercado/nfl_lineas.csv`).
- Universo: cada lado (fútbol: local, empate, visita; NFL: local, visita) con cuota entre 1.80 y 3.00 al precio de referencia
  (fútbol: mejor precio; NFL: cierre).
- Reglas fijas (no se ajusta nada):
  - R0 todo el universo (línea base).
  - R1 el modelo da más probabilidad que la que pide la cuota (p > 1/cuota).
  - R2 como R1 con al menos 3 pp de margen.
  - R3 el lado es el favorito del modelo (el más probable).
  - R4 R2 más un ángulo a favor: fútbol, un día o más de descanso que el rival; NFL, el lado es el local.
- Métricas: apuestas, por temporada, acierto, cuota media, ROI a 1 u, IC 95 % por bootstrap, P(ROI > 0) con bootstrap bayesiano
  (pesos de Dirichlet), y la brecha media contra el cierre de Pinnacle (solo fútbol).
- Partición: 70 % más antiguo y 30 % más reciente. Una regla "pasa" si en el 30 %: n ≥ 300, ROI > 0 y P(ROI > 0) ≥ 0.90,
  y además ROI > 0 en el 70 %. k = 5 reglas × 2 deportes = 10.

## Resultado (30 % final mirado una vez; k = 10)

Fútbol (mejor precio; 21,921 lados con cuota y predicción del modelo; prueba desde 2025-04-13):
- R0 todo 1.80–3.00: 70 % +1.43 % | 30 % n 1,745, acierto 41.9 %, cuota 2.38, ROI −3.33 % [−8.8, +2.3], P(ROI>0) 0.12.
- R1 modelo > cuota: 70 % −2.79 % | 30 % n 637, ROI −13.11 % [−22.2, −4.0], P 0.00.
- R2 margen 3 pp: 70 % −4.25 % | 30 % n 345, ROI −14.81 % [−26.6, −2.7], P 0.01.
- R3 favorito del modelo: 70 % +0.42 % | 30 % n 1,268, acierto 43.1 %, cuota 2.26, ROI −5.23 % [−11.4, +1.1], P 0.06.
- R4 R2 + descanso a favor: 30 % n 97, muestra insuficiente.
- Brecha media contra el cierre de Pinnacle de las apuestas tomadas: entre −2.9 % y −4.0 %.

NFL (cierre de una casa; 4,202 lados; prueba desde 2023-12-31):
- R0 todo: 30 % n 435, ROI −5.98 % [−16.7, +4.7], P 0.12.
- R1, R2, R3, R4: menos de 300 apuestas en la prueba (muestra insuficiente). R3 favorito del modelo: n 133, acierto 48.9 %,
  cuota 2.14, ROI +1.05 % [−16.3, +18.6], P 0.54.

Veredicto: **ninguna regla pasa.** En fútbol, seguir al modelo a cuota alta empeora el resultado (el modelo de fútbol no le gana
al cierre: peso medido 0.00); lo que más pesa es el precio, y las apuestas tomadas quedan 3–4 % por debajo del cierre de Pinnacle.
