# Hipótesis (escrita antes de ver resultados) — 2026-10-09

Ángulos situacionales cualitativos (motivación y tabla), tanda 2. Script: `utilidades/minar_cualitativos.py`.
Deportes: NHL, NBA, NFL, béisbol (MLB, NPB, KBO, LMP, LVBP, LIDOM, ABL) y fútbol (7 ligas).

Definiciones (todo as-of; "fuerte" = % de victorias ≥ 0.60 en la temporada con 8 juegos o más; "débil" ≤ 0.40;
temporada = racha de juegos sin un hueco de más de 60 días; en fútbol el empate cuenta medio):
- Q1 Revancha: perdió el último enfrentamiento de la temporada contra este rival. Esperado: + para ese equipo.
- Q2 Bajón: viene de ganarle a un fuerte y hoy enfrenta a un débil. Esperado: − para ese equipo.
- Q3 Mirando adelante: hoy enfrenta a un débil y su siguiente rival es fuerte. Esperado: −.
- Q4 Sándwich: rival anterior y siguiente fuertes, hoy débil. Esperado: −.
- Q5 Primer juego en casa de la temporada (el local). Esperado: +.
- Q6a Racha de 5 o más derrotas. Esperado: + (regresión que el modelo no alcance a ver).
- Q6b Racha de 5 o más victorias. Esperado: −.
- Q7 Fin de temporada (último 15 % de sus juegos, temporada de 20 o más): equipo débil (≤ 0.40) contra rival ≥ 0.55.
  Esperado: − para el débil.
- Q8 NFL partido divisional: el local. Esperado: − (la ventaja de casa se achica).
- Q9 NFL entrenador nuevo a media temporada (primeros 3 juegos tras el cambio). Esperado: +.
Partidos donde los dos equipos están en la misma situación se excluyen de ese ángulo.

Medición:
1. Residuo fuera de muestra contra el modelo (mismo evaluador y criterio que la tanda 1: 70/30, log-loss pareado,
   z ≥ 2.0, dos mitades, calibración ≤ 0.04, n activo ≥ 300, dirección registrada). k = número de pruebas con resultado.
2. TMLE (descriptivo, toda la muestra): efecto sobre la probabilidad de que gane el equipo en la situación,
   ajustado por la probabilidad del modelo para ese equipo y por si juega en casa. IC 95 %.
Pendiente y fuera de esta tanda: eliminación en playoffs (hay que reconstruir las series) y derbis de fútbol (falta la tabla).

## Resultado (30 % final mirado una vez; k = 38 pruebas con resultado)

Residuo fuera de muestra: **ninguno pasa.** La mayoría queda en muestra insuficiente (menos de 300 casos activos en la prueba):
estas situaciones son raras. Con muestra: revancha (Q1) en NHL, NBA, béisbol y fútbol, y rachas de 5 en béisbol: z entre −1.2 y +0.8.

TMLE (toda la muestra, dentro de muestra; efecto para el equipo en la situación) que excluye el cero:
- NHL Q5 primer juego en casa: +5.7 pp [+2.6, +8.8] (269 casos). En la prueba fuera de muestra no se sostiene (89 casos).
- NBA Q2 bajón tras ganarle a un fuerte: +10.3 pp [+5.3, +15.4] (223), al revés de lo registrado.
- NBA Q7 débil contra en contienda al final: −24.2 pp [−26.6, −21.8] (166); residuo fuera de muestra −16.0 pp en 77 casos.
  Coincide con el tanqueo de la NBA, pero el intervalo es demasiado estrecho para 166 casos: la exposición está casi
  determinada por la fuerza (positividad pobre) y el TMLE exagera la precisión. A revisar con otro ajuste.
- Béisbol Q2 bajón: −2.4 pp [−4.7, −0.1] (152). Béisbol Q7: +2.2 pp [+0.6, +3.8] (224), al revés de lo registrado.
- Fútbol Q5 primer juego en casa: −3.1 pp [−5.7, −0.5] (348). Fútbol Q6a racha de 5+ derrotas: −8.9 pp [−12.7, −5.0] (245):
  el que viene perdiendo sigue perdiendo más de lo que dice el modelo (el modelo reacciona lento).
- NFL Q6b racha de 5+ victorias: +9.5 pp [+3.3, +15.8] (289), al revés de lo registrado: mismo patrón, el modelo reacciona lento.
Ocho de unas 38 estimaciones excluyen el cero; por azar se esperarían unas 2. Son candidatos para medir otra vez con más
temporadas, no reglas. Sin medir: eliminación en playoffs y derbis de fútbol.
