# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Liga: MLB y KBO (por separado). Mercado: ganador.
Señal: fuerza dinámica de cada equipo con filtro de Kalman sobre el diferencial de carreras.
  Estado: fuerza s_t ~ N(m, P). Cada día de juego: P += q (proceso). Observación: margen = s_local − s_visita + h + ruido
  (σ² = varianza del margen de la liga). Al cambiar de temporada la fuerza regresa 1/3 a 0 y P se infla.
  Señal = (m_local − m_visita) / sqrt(σ² + P_local + P_visita): diferencia de fuerza ajustada por su incertidumbre.
Contra qué: residuo del modelo actual de validación (logística ELO + box, más abridores en KBO).
  logit p' = logit p_modelo + β·señal, β ajustado en el 70 % más antiguo.
Variantes (k = 2): q baja (0.002 σ² por día) y q alta (0.01 σ² por día).
Dirección esperada: β > 0 (la fuerza dinámica corrige lo que el ELO tarda en ver).
Métrica: log-loss; error pareado contra el modelo actual y contra la tasa base. 30 % final, una vez.
Criterio de la casa: n ≥ 300 en prueba, z ≥ 2.0, mejora en las dos mitades, calibración ≤ 0.04.

## Resultado (30 % final, mirado una vez)
- MLB (2,612 juegos desde 2025-09-14): q baja beta −0.16, vs modelo +0.59 milésimas (z 1.48); q alta +0.65 (z 1.43). No pasa.
  Beta negativo: la señal sirve para frenar al modelo cuando la fuerza es incierta, pero sin llegar a z 2.
- KBO (1,086 juegos desde 2025-06-11): empeora al modelo (−0.50 y −0.33). No pasa.
Veredicto: NO PASA en ninguna liga (k = 2). El ELO + box + abridores ya captura la fuerza dinámica.
