# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Circuito: ATP y WTA (por separado, al mejor de 3 y de 5). Mercados: breaks totales y games totales.
Problema: el modelo usa el % de puntos ganados al saque de cada jugador en TODA su carrera, sin superficie ni torneo.
Señales (as-of, solo partidos anteriores):
  V1 velocidad del torneo: promedio, en ediciones y rondas anteriores del mismo torneo, de
     (% real de puntos ganados al saque − % esperado por la carrera de los dos jugadores).
  V2 saque en la superficie: (% al saque del jugador en esta superficie − su % de carrera), sumado para los dos.
Dirección esperada: más velocidad o mejor saque en superficie → menos breaks y más games.
Contra qué: residuo del modelo actual (breaks y games esperados ya con el ajuste de sesgo as-of).
Ajuste lineal del residuo en el 70 % más antiguo; prueba en el 30 % reciente, una vez.
Variantes (k = 3): V1, V2, V1+V2. Métricas: MAE y MSE del conteo, y log-loss del O/U en la línea ~promedio.
Criterio de la casa: n ≥ 300, z ≥ 2.0, mejora en las dos mitades.

## Resultado (30 % final por grupo, mirado una vez; k = 3)
Breaks (todas las combinaciones pasan, z de 3 a 11, las dos mitades):
- ATP bo3 (15,816): V1+V2 MAE +0.022 (z 10.7), O/U +5.8 milésimas (z 7.1). Coef V1 −15.3, V2 −2.8.
- ATP bo5 (3,767): V1 MAE +0.073 (z 7.9), O/U +15.0 (z 5.0). V1+V2 O/U +14.7 (z 4.9).
- WTA bo3 (10,232): V1+V2 MAE +0.017 (z 6.8), O/U +3.9 (z 5.1).
Games: mixto. Mejora el MSE (z ~2.3) pero empeora el MAE (ATP bo3 z −4.5); ATP bo5 y WTA no pasan. No se adopta.
Veredicto: PASA en breaks (V1+V2, o V1 solo en ATP bo5). Dirección la esperada: torneo rápido → menos breaks.
Pendiente: aprobación de Alejandro para meterlo al modelo de tenis (breaks) y re-validar.
