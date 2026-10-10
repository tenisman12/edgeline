# Ángulos de hockey juntos: bayesiano jerárquico, boosting y red neuronal (10-oct-2026)

Script: `utilidades/minar_angulos_bayes_hockey.py` · resultados: `trabajo/minar/2026-10-10_bayes_hockey_resultados.json`

## Hipótesis (registrada antes de correr)
Los ángulos de ganador de hockey no pasan uno por uno (k 154 en SHL/Liiga/AHL/DEL, ninguno pasa). Juntos, con efectos
compartidos entre ligas, mejoran la predicción as-of del modelo fuera de muestra: z ≥ 2.0, las dos mitades a favor y
|p media − tasa real| ≤ 0.04.

## Diseño
- 14,820 partidos con predicción as-of del modelo de hockey de cada liga: NHL 10,487 (2018-10 a 2026-10), SHL 372,
  Liiga 1,006, AHL 2,250, DEL 705.
- 29 ángulos con las definiciones del minado (x > 0 favorece al local): H1-H8, H13-H18, H21-H23, Q1-Q7, S1-S4, S7, S8.
- Modelo: `logit P = a_liga + b_liga·logit(p_modelo) + Σ (μ_k + δ_liga,k)·x_k/sd_k`, con μ_k ~ N(0, τ²) y δ ~ N(0, σ²) (MAP).
  La base es el mismo modelo sin ángulos (la mejora no puede venir de recalibrar).
- τ ∈ {0.01…0.20} y σ ∈ {0.005, 0.03, 0.08} se eligen con el último 20 % del entrenamiento.
- Walk-forward mensual desde el 40 % de los partidos (prueba: 9,024 partidos, 2023-03 a 2026-10).
- Misma prueba con HistGradientBoosting (profundidad 3) y un MLP de 16 neuronas sobre logit(p), liga y ángulos.

## Resultado

| Grupo | n | Mejora log loss (milésimas) | z | Mitades | Brier | Veredicto |
|---|---|---|---|---|---|---|
| Hockey, bayesiano | 9,024 | −0.347 | −0.95 | −0.69 / −0.00 | −0.08 % | no pasa |
| NHL | 4,691 | −0.176 | −0.27 | −0.22 / −0.13 | −0.04 % | no pasa |
| SHL | 372 | +0.064 | +0.10 | −0.82 / +0.95 | −0.02 % | no pasa |
| Liiga | 1,006 | −0.506 | −0.75 | −1.05 / +0.04 | −0.11 % | no pasa |
| AHL | 2,250 | −0.145 | −0.34 | −0.89 / +0.60 | −0.03 % | no pasa |
| DEL | 705 | −2.121 | −3.33 | −3.76 / −0.49 | −0.44 % | no pasa (empeora) |
| Boosting | 9,024 | −0.517 | −0.54 | +0.41 / −1.45 | −0.12 % | no pasa |
| Red neuronal | 9,024 | −21.786 | −9.13 | −28.6 / −15.0 | −4.02 % | no pasa (sobreajusta) |

- La validación interna escoge casi siempre el τ más chico de la rejilla (0.01): los datos piden encoger los ángulos a casi cero.
- Con todo el historial, el ángulo común más grande mueve 1.0 pp (Q7 −1.03, H2 −0.99, S8 +0.88, Q5 +0.83, S4 +0.80);
  la mayoría queda debajo de 0.5 pp.

## Conclusión
Los ángulos situacionales no agregan información al modelo de hockey, ni solos ni juntos, ni con un modelo flexible. El
modelo ya trae el descanso de la segunda noche (`_aplicar_b2b`) y la fuerza reciente por ELO; lo demás es ruido.
Los ángulos siguen como contexto (regla del 9-oct) y no se les da peso.
Prueba contra el mercado: no hay cuotas históricas de hockey en el repo (empiezan el 1-oct-2026); se mide en vivo con
`salida/historial_angulos.csv`.
