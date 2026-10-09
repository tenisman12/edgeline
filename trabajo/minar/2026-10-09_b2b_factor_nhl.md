# Hipótesis (escrita antes de ver resultados) — 2026-10-09

Reescalar el factor de segunda noche del modelo de hockey. Script: `utilidades/minar_b2b_factor_nhl.py`.

- Hoy `modelos/hockey.py` multiplica los goles esperados del equipo en segunda noche por f_of (≈0.952) y los del
  rival por f_df (≈1.027), factores estimados as-of. Eso vale unos ±3.5 pp; el TMLE del 9-oct mide +7.5 / −8.3 pp.
- Candidato: elevar los dos factores a una potencia k (k = 1 es el modelo actual). Rejilla k ∈ {1, 1.5, 2, 2.5, 3}.
- Se elige k con el log-loss del 70 % más antiguo (predicción as-of de `entrenar`, recalibrada con logística en ese 70 %).
- Prueba una sola vez en el 30 % más reciente: k elegido contra k = 1, log-loss pareado.
- Pasa si: z ≥ 2.0, mejora en las dos mitades, calibración ≤ 0.04 en los partidos con alguien en segunda noche.
- Si pasa: se aplica en `modelos/hockey.py` como `EDGELINE_NHL_B2B_K` (aprobado por Alejandro el 9-oct, condicionado a que pase).
  Si no pasa: no se toca el modelo.

## Resultado (30 % final mirado una vez)

- Log-loss en el 70 %: k 1.0 0.667335 · k 1.5 0.667162 · k 2.0 0.667257 · k 2.5 0.667589 · k 3.0 0.668119. Elegido k = 1.5.
- Prueba (3,142 partidos; 759 con alguien en segunda noche): k 1.5 contra k 1.0, +0.395 milésimas, **z +1.19**,
  mitades +0.568 / +0.223, calibración −0.034.
- **Veredicto: no pasa. `modelos/hockey.py` no se toca.** Duplicar el factor (k 2, lo que sugiere el TMLE) fue peor que 1.5
  ya en el 70 %: el efecto total de la segunda noche es grande, pero el modelo de goles no gana precisión al exagerarlo.
