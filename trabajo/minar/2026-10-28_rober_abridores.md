# Angulos de abridor de Roberto (28-oct-2026)

LMP 2014-2025, 4130 juegos con los dos abridores. Base ELO y base ELO + FIP regresado (coef FIP 0.197 logit por punto). Exceso = acierto real - esperado (pp); z entre parentesis. Regla: n >= 300, |z| >= 2, mitades del mismo signo, en la direccion de la hipotesis. Sin cuotas: no mide ROI.

| Cod | Angulo | n | Exceso ELO | Exceso ELO+FIP | Mitades | Temporadas + | Veredicto |
|---|---|---|---|---|---|---|---|
| R4 | contra el abridor suertudo (su FIP 1.5+ peor que su ERA) | 647 | +1.50 (0.77) | +1.01 (0.52) | +0.82 / +1.16 | 7/12 | no pasa |
| R5 | abridor con peor ERA pero mejor FIP que el rival | 868 | +3.09 (1.84) | +2.01 (1.19) | +4.65 / -0.48 | 6/12 | no pasa |
| R6 | contra el abridor caliente (su equipo +3 o mas en sus aperturas) | 1165 | -1.13 (-0.78) | -0.68 (-0.47) | -1.99 / +0.41 | 3/12 | no pasa |
| R7 | underdog con mejor abridor por FIP | 934 | +1.67 (1.03) | +0.18 (0.11) | +1.11 / -0.72 | 5/12 | no pasa |
| R8 | favorito con peor abridor por FIP | 934 | -1.67 (-1.03) | -0.18 (-0.11) | -1.11 / +0.72 | 7/12 | no pasa |
| R9 | primera apertura de la temporada | 1136 | -1.40 (-0.95) | -1.33 (-0.9) | -0.93 / -1.64 | 3/12 | no pasa |
| R10 | abridor con 8 a 14 dias de descanso | 718 | -3.60 (-1.94) | -3.48 (-1.88) | -3.29 / -3.64 | 2/12 | no pasa |
| R11 | a favor del abridor caliente (su equipo +3 o mas en sus aperturas) | 1165 | +1.13 (0.78) | +0.68 (0.47) | +1.99 / -0.41 | 9/12 | no pasa |

Todos quedan como contexto en nucleo/angulos (R4-R11) y se registran en vivo en salida/historial_angulos.csv para medirlos con cuotas reales. R6/R11 usan el record del equipo en las aperturas del abridor como sustituto del pitcher profit en unidades.
