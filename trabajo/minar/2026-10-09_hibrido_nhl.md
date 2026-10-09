# Hipótesis (escrita antes de ver resultados) — 2026-10-09

Sistema híbrido NHL: Super Learner (predicción) + TMLE (efecto de los ángulos). Script: `utilidades/sistema_hibrido_nhl.py`.

## Super Learner
- Datos: 10,473 predicciones as-of del modelo de hockey (2018-19 a hoy), cada una con variables calculadas solo con lo anterior.
- Biblioteca (6 aprendices):
  1. modelo actual recalibrado (logit p)
  2. ELO solo (diferencia de ELO as-of)
  3. modelo + fatiga (H1, H2, H4, H6, H7), logística con ridge
  4. modelo + tiros y PDO de los últimos 10 (diferencia local − visita) + diferencial de goles L10, logística con ridge
  5. todo junto, logística con ridge
  6. gradient boosting (HistGradientBoosting, profundidad 3, 200 iteraciones, tasa 0.05) con todas las variables
- Pesos: combinación convexa de probabilidades que minimiza el log-loss de predicciones fuera de pliegue
  (validación cruzada hacia adelante en el tiempo, 5 pliegues, dentro del 70 % más antiguo).
- Prueba: 30 % más reciente, se mira una vez.
- Hipótesis: el Super Learner mejora el log-loss del modelo actual recalibrado.
  Pasa si z ≥ 2.0 (pareado), mejora en las dos mitades y calibración |p media − tasa| ≤ 0.04.
- Se reporta además la probabilidad de acierto: % de veces que gana el lado que el sistema da como favorito,
  por tramo de confianza (50–55, 55–60, 60–65, 65–70, 70+ %).
- Sin mercado (no hay cierres históricos de NHL) y sin tu lectura (no hay historial suficiente): se agregan cuando existan.

## TMLE (estimación, sin veredicto de pasa/no pasa)
Efecto causal sobre la probabilidad de que gane el local (diferencia de riesgos, pp, IC 95 %), ajustando por la fuerza
de los dos equipos antes del partido (logit de la probabilidad del modelo SIN su ajuste de descanso, diferencia de ELO,
diferencial de goles L10, tiros L10 cuando hay):
- E1 visita en segunda noche y local descansado (contra: ninguno en segunda noche)
- E2 local en segunda noche y visita descansada (contra: ninguno)
- E3 visita en su tercer juego en 4 noches (contra: no)
- E4 visita viene de prórroga o shootout (contra: no)
- E5 local perdió su último juego por 4 o más (contra: no)
- E6 visita con 2 o más juegos más que el local en los últimos 7 días (contra: misma carga)
Lo que el modelo ya pone por segunda noche (unos ±3.5 pp) se compara contra E1 y E2.

## Resultado (30 % final desde 2024-03-21, 3,142 partidos, mirado una vez)

Super Learner
- Pesos: todo junto con ridge 0.677, modelo + tiros/PDO 0.277, gradient boosting 0.046; los demás 0.
- Log-loss: modelo 0.67247 → super learner 0.67120 (+1.27 milésimas), **z +0.93**, mitades +4.89 / −2.36.
  Brier 0.23992 → 0.23939. Calibración −0.008. **Veredicto: no pasa.**
- Acierto del favorito: 57.1 % los dos. Por confianza (prometido → real):
  - modelo: 50–55 % 52.5 → 51.5 (n 1,330) · 55–60 % 57.3 → 55.4 (980) · 60–65 % 62.2 → 65.9 (542) · 65–70 % 67.0 → 68.6 (223) · 70 %+ 72.5 → 83.6 (67)
  - super learner: 50–55 % 52.5 → 50.3 (1,049) · 55–60 % 57.3 → 54.5 (851) · 60–65 % 62.3 → 58.5 (636) · 65–70 % 67.2 → 68.3 (353) · 70 %+ 74.2 → 74.3 (253)

TMLE (toda la muestra; efecto total sobre la probabilidad del local, ajustado por fuerza sin el ajuste de descanso del modelo)
- E1 visita en segunda noche: +7.5 pp [+4.9, +10.1] (el modelo pone unos +3.5)
- E2 local en segunda noche: −8.3 pp [−12.8, −3.9] (el modelo pone unos −3.5)
- E3 visita en tercer juego en 4 noches: +3.1 pp [+0.8, +5.3]
- E4 visita viene de prórroga (solo juegos con dato): −2.7 pp [−6.3, +0.8]
- E5 local perdió por 4+: +1.0 pp [−2.8, +4.8]
- E6 visita con 2+ juegos más en 7 días: +4.4 pp [−0.6, +9.4]
