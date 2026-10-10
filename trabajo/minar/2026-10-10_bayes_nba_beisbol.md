# Ángulos juntos en básquet y béisbol: bayesiano jerárquico, boosting y red neuronal (10-oct-2026)

Script: `utilidades/minar_angulos_bayes.py --deporte nba|beisbol --ml` (usa el modelo de `minar_angulos_bayes_hockey.py`).
Resultados: `2026-10-10_bayes_nba_resultados.json`, `2026-10-10_bayes_beisbol_resultados.json`.

## Hipótesis (registrada antes de correr)
Los ángulos de ganador sin peso, juntos y con efectos compartidos entre ligas, mejoran la predicción as-of de producción
fuera de muestra (z ≥ 2.0, las dos mitades a favor, calibrado). La base ya trae las capas aprobadas con el beta de
plataforma.py: K14 ausencias en NBA (0.308 por 48 min) y S4 frío contra caliente en béisbol (0.161).

## Diseño
Igual que hockey: logística jerárquica con offset logit(p), a_liga y b_liga en la base y en el modelo; τ y σ elegidos con
el último 20 % del entrenamiento; walk-forward mensual desde el 40 % de los partidos. Mismo walk-forward con
HistGradientBoosting y un MLP de 16.
- Básquet (NBA, NCAAMB): K1-K4, K8a, K8b, K10, K11, K12, K13, Q1-Q7, S1-S3, S7, S8. 21,386 partidos.
- Béisbol (MLB, NPB, KBO, LMP, LVBP, LIDOM, ABL): B1, B2, B5, B10-B15, B18, B19, B21, B25, Q1-Q7, S1-S3, S7, S8.

## Resultado

| Grupo | n | Mejora (milésimas) | z | Mitades | Brier | Veredicto |
|---|---|---|---|---|---|---|
| Básquet, bayesiano | 13,897 | +1.222 | +1.75 | +0.49 / +1.95 | +0.25 % | no pasa |
| · NBA | 2,544 | +0.199 | +0.13 | +0.15 / +0.25 | −0.01 % | no pasa |
| · NCAAMB | 11,353 | +1.452 | +1.86 | +0.55 / +2.36 | +0.32 % | no pasa (cerca) |
| Básquet, boosting | 13,897 | +1.124 | +1.40 | +0.85 / +1.39 | +0.24 % | no pasa |
| Básquet, red neuronal | 13,897 | −3.177 | −2.06 | ambas negativas | −0.61 % | no pasa |
| Béisbol, bayesiano | 12,803 | −0.302 | −1.20 | −0.51 / −0.09 | −0.06 % | no pasa |
| · MLB | 7,115 | −0.287 | −0.78 | −0.59 / +0.01 | −0.06 % | no pasa |
| · NPB | 2,526 | −0.928 | −2.44 | ambas negativas | −0.19 % | empeora |
| · KBO | 2,095 | −0.065 | −0.10 | +0.02 / −0.15 | −0.01 % | no pasa |
| · LMP | 642 | +0.769 | +0.67 | +3.59 / −2.06 | +0.16 % | no pasa |
| Béisbol, boosting | 12,803 | −1.534 | −3.15 | ambas negativas | −0.30 % | no pasa |
| Béisbol, red neuronal | 12,803 | −6.456 | −5.95 | ambas negativas | −1.17 % | no pasa |

## Lectura
- Béisbol: nada. Con S4 ya en la base, lo demás no agrega; boosting y red empeoran.
- Básquet: es el único caso con las dos mitades a favor (NCAAMB z 1.86, básquet z 1.75), pero no llega a 2.0. No se le da
  peso. Queda registrado como candidato a medir en vivo (historial_angulos.csv) sin cambiar la hipótesis ni la rejilla.
- Los efectos "comunes" de ángulos con menos de ~150 partidos activos (B1, Q5 en béisbol) salen grandes por la
  estandarización (x/sd); no son confiables y no cuentan para el veredicto, que es fuera de muestra.
