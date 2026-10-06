# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Ligas: NHL, MLB, KBO, NBA (por separado). Mercado: ganador.
Señal: osciladores as-of de cada equipo (diferencia local − visita), calculados solo con partidos anteriores y con la
misma base de producción (últimos 40 juegos, cruzando temporadas):
  Básicos: forma (% victorias L10 − base), ataque (GF L10 / base − 1), defensa (GA L10 / base − 1), dif5 (dif L5 − base).
  Técnicos: RSI10 del diferencial, histograma MACD (EMA5 − EMA20 del diferencial, menos su EMA9), estocástico del ELO (14),
            impulso del ELO en 10 juegos, residuo pitagórico (% victorias − esperado por goles, base 40).
Contra qué: residuo del modelo actual en walk-forward (bloques de 30 días): logit p' = logit p + Σ β·señal, β ajustado con
  regularización en el 70 % más antiguo; prueba en el 30 % reciente, una vez.
Variantes (k = 3): básicos, técnicos, todos.
Dirección esperada: sin dirección fija (puede ser impulso o reversión); se reporta el signo de cada β.
Métrica: log-loss; error pareado contra el modelo. Criterio de la casa: n ≥ 300, z ≥ 2.0, mejora en las dos mitades, calibración ≤ 0.04.

## Resultado (30 % final, mirado una vez; k = 3 por liga)
- NHL (1,080): básicos +0.14 milésimas (z 0.13); técnicos −2.90 (z −1.75); todos −2.37. NO PASA.
- NBA (1,385 desde 2025-04-23): básicos +8.83 (z 3.09, mitades +11.6/+6.0); técnicos +9.21 (z 3.17); todos +10.63 (z 3.22,
  mitades +7.9/+13.4), calibración 0.553 vs 0.554. PASA. Signos (todos): forma −0.12 (reversión), ataque +0.16 (el ataque
  caliente sigue), defensa −0.08, dif5 +0.09, RSI10 +0.17.
- MLB (2,609): ~0 (z ≤ 0.84). NO PASA.
- KBO (1,086): ~0. NO PASA.
Pendiente antes de aplicar en NBA: la base de esta prueba es el modelo sin las capas de producción (descanso, b2b, net rating L10).
Hay que repetir la prueba encima de esas capas para no contar dos veces la misma información.
