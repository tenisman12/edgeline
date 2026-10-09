# Hipótesis (escrita antes de ver resultados) — 2026-10-09

Índice de fatiga en NHL con encogimiento bayesiano. Script: `utilidades/minar_fatiga_nhl.py`.

- Base: predicción as-of del modelo de hockey (lista `cal` de `entrenar()`, ya trae su factor de segunda noche),
  recalibrada en el 70 % más antiguo: logit(q) = a·logit(p) + b.
- Índice: los cinco componentes de cansancio de la tanda 1, firmados hacia el local, ajustados JUNTOS en el 70 %:
  H1 visita en segunda noche, H2 local en segunda noche, H4 un día de diferencia de descanso,
  H6 tercer juego en 4 noches, H7 carga de 7 días.
- Encogimiento: prior normal centrado en 0 con τ = 0.10 en logit para cada componente (fijado antes de ver datos:
  "después del modelo, un ángulo de calendario rara vez mueve más de ±5 pp"). Equivale a ridge con λ = 1/τ² = 100
  sobre los cinco coeficientes; a y b sin penalización.
- Dirección esperada: el índice favorece al equipo descansado (coeficiente neto del índice > 0 en el 30 %).
- Prueba: 30 % más reciente, se mira una vez. Log-loss pareado base − índice.
- Pasa si: z ≥ 2.0, mejora en las dos mitades, |p media − tasa real| ≤ 0.04 en los partidos con índice ≠ 0,
  n activo ≥ 300. k = 1 (una sola hipótesis).
- Contra el mercado: no hay cierres históricos de NHL; queda pendiente con las fotos de 2026.

## Resultado (30 % final mirado una vez; k = 1)

- Coeficientes encogidos (τ 0.10): H1 +1.6 pp, H2 −2.3 pp, H4 +0.5, H6 +1.1, H7 +0.5 por unidad.
- Prueba (3,142 partidos desde 2024-03-21; 2,156 con índice ≠ 0): log-loss +0.700 milésimas, **z +1.42**,
  mitades +0.936 / +0.464, calibración −0.011.
- El modelo se queda corto en la dirección del índice: +3.0 pp en todos los activos y +3.1 pp con |índice| ≥ 0.08 (n 641).
- **Veredicto: no pasa** (z < 2). Mejor que H1 solo (z 1.29), con la misma dirección en las dos mitades.
  Se vuelve a medir con la temporada 2026-27 completa.
