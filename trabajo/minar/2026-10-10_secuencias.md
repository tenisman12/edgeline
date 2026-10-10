# Red convolucional, random forest y TMLE sobre los ángulos (10-oct-2026)

Script: `utilidades/minar_angulos_secuencias.py --deporte hockey|nba|beisbol` (filas de `minar_angulos_bayes*.py`).
Resultados: `2026-10-10_secuencias_<deporte>_resultados.json`.

## Hipótesis (registradas antes de correr)
- CNN: una red convolucional 1D que lee los últimos 10 partidos de cada equipo (ganó, local, descanso, residuo contra el
  modelo, días desde ese juego) mejora la predicción as-of de producción fuera de muestra (z ≥ 2.0, las dos mitades, calibrado).
- RF: un random forest con logit(p), liga y todos los ángulos mejora la predicción (mismo criterio).
- TMLE: efecto de cada ángulo ajustado por la p del modelo y la sede, en toda la muestra, con corte de Bonferroni.
Base: la recalibración por liga sin ángulos. Walk-forward: reentrena cada 3 meses, predice cada mes.

## Resultado (fuera de muestra)

| | Hockey (n 9,024) | Básquet (n 13,897) | Béisbol (n 12,803) |
|---|---|---|---|
| CNN, semilla 0 | z +0.96 (NHL −2.72) | **z +2.38 pasa** (NCAAMB **+2.67**, NBA −0.84) | z −0.12 |
| Random forest | z −1.76 | z −6.83 | z −2.79 |

Estabilidad de la CNN en básquet (cuatro semillas):

| Semilla | Básquet | NCAAMB | NBA |
|---|---|---|---|
| 0 | +2.38 pasa | +2.67 pasa | −0.84 |
| 1 | +2.24 pasa | +2.30 pasa | +0.11 |
| 2 | +1.66 | +2.17 pasa | −1.53 |
| 3 | +0.85 | +1.26 (mitades −1.09 / +2.93) | −1.02 |

NCAAMB pasa con 3 de 4 semillas; calibración dentro de ±0.013 y peor decil ≤ 0.02. Mejora chica: +0.9 a +1.4 milésimas de
log loss, Brier +0.23 a +0.31 %. NBA no pasa con ninguna.

## TMLE (toda la muestra, dentro de muestra)
- Hockey: pasan Bonferroni H2 local en segunda noche (−6.6 pp, z −5.61) y H1 (+2.7 pp, z +3.45). Revisado aparte: H2 en la
  zona de prueba vale −4.3 pp crudo (n 355) y en walk-forward solo, z −0.43: el efecto se encoge con el tiempo y no predice.
- Básquet: K8b, K10, K1, Q2, Q4 pasan Bonferroni dentro de muestra; juntos en el bayesiano dan z 1.75 fuera de muestra.
- Béisbol: S8, B1 y Q7 salen con z ±17 con 70 a 219 expuestos: el TMLE se rompe con pocos expuestos (propensión en el borde).
- Lección: un efecto dentro de muestra, aun con Bonferroni, no garantiza que prediga. Solo cuenta el walk-forward.

## Conclusión
- Lo único que pasa es la CNN en NCAAMB, y depende de la semilla (3 de 4). Candidato: falta un ensamble de 5 semillas
  con walk-forward y medirlo en vivo la temporada 2026-27 antes de llevarlo a aprobación. No se aplica nada.
- Lectura probable: en NCAAMB el modelo tarda en ajustar la fuerza de cada equipo; los residuos recientes del propio modelo
  (canal 4 de la secuencia) corrigen ese retraso. En NBA, hockey y béisbol no aparece.
- Random forest pierde en los tres deportes.
