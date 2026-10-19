# Selección de apuestas: modelo contra mezcla con Pinnacle (18-oct-2026)

**Pregunta.** ¿Qué habría pasado del 1 al 18 de octubre si la probabilidad de la apuesta saliera de mezclar el modelo con
Pinnacle en lugar del modelo solo?

**Datos.** 947 lecturas calificadas con p del modelo, p de Pinnacle sin vig al registrar (`clv_detalle.csv`, lista modelo)
y cuota registrada (`historial_predicciones_calificado.csv`): 485 ganador, 349 total, 113 spread. 165 filas no cruzaron.
Script: `utilidades/simular_mezcla_pinnacle.py`. Reglas de la simulación: EV ≥ 2 %, cuota ≥ 1.70, 1 u, solo el lado del
modelo, ganador y total.

**Quién predice mejor (log loss).**
- Todo: Pinnacle mejor por 19.2 milésimas (z 2.46).
- Ganador: Pinnacle mejor por 18.3 (z 1.79). La mejor mezcla es w 0.10–0.25 (0.6166 contra 0.6174 de Pinnacle solo).
- Total: Pinnacle mejor por 27.0 (z 2.44). La mejor mezcla es w = 0 (el modelo no agrega).
- Spread: empate; ahí la mezcla w 0.5 mejora (0.7064 contra 0.7224).
- Por liga: NCAAF ganador −42.5 (z −2.04) y total −47.5 (z −2.20); NFL total −64.8 (z −1.62). A favor del modelo, sin
  significancia: ATP ganador +16.6 (z 0.65), WTA ganador +22.7 (z 0.95), KBO total +20.0 (z 0.82).

**Simulación de apuestas.**
- Modelo solo (criterio actual): 314 apuestas, 141 ganadas (44.9 %), −37.32 u (−11.9 %).
- Mezcla w 0.5: 217, 47.0 %, −14.77 u. w 0.35: 161, 46.6 %, −10.82 u. w 0.25: 106, 40.6 %, −18.15 u.
- Mezcla w 0.1: 22, 45.5 %, +1.01 u.
- Solo Pinnacle: 2 apuestas.
- Con EV ≥ 4 %: modelo −30.40 u en 280; mezcla w 0.25 −2.62 u en 64.
- Por liga con el modelo solo: NCAAF total −19.74 u (115), NCAAF ganador −5.77 (30), NFL total −5.35 (32), NHL total −5.48
  (13); ATP ganador +6.25 (13), KBO total +5.19 (22), WTA ganador +3.17 (11).

**Lectura.** Ninguna regla basada en el modelo deja ganancia con muestra suficiente en estas dos semanas. La mezcla reduce
la pérdida sobre todo porque apuesta menos. Los aciertos reales quedan cerca de lo que esperaba Pinnacle y debajo de lo que
esperaba el modelo en todas las variantes. Muestra corta (18 días); se repite con más semanas.
