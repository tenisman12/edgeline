# Métodos numéricos y vectoriales en béisbol (20-oct-2026)

Código: `trabajo/minar/2026-10-20_metodos_numericos.py`. Resultados: `2026-10-20_metodos_numericos_resultados.json`.
No toca producción.

## Hipótesis (escrita antes de ver resultados)
Seis vistas nuevas del ganador y del total mejoran al modelo actual (MEDIA3 = ELO + logística + carreras; totales = capa de producción), sobre todo en el arranque de temporada (primeros 10 juegos de cada equipo):
- M1 vectores: cada equipo es un vector (ataque, defensa) en un modelo log-lineal de carreras, actualizado juego a juego.
- M2 Kalman: fuerza de cada equipo como estado oculto con incertidumbre; prior = temporada pasada encogida.
- M3 vecinos: los K juegos históricos más parecidos en el vector de features (K elegido con la última temporada previa).
- M4 Markov: cadena de 24 estados (bases × outs) con el vector de tasas por turno (BB+HBP, 1B, 2B, 3B, HR, out), bateo propio contra pitcheo rival (log5 multinomial); distribución exacta de carreras por programación dinámica.
- M5 boosting: gradient boosting sobre el vector completo de features.
- M6 pesos: apilado logístico de todas las vistas, con pesos aprendidos de lo anterior en lugar del promedio simple.

Cada vista se prueba sola y como capa sobre la base: logit p' = logit base + c + b·(logit vista − logit base).

## Protocolo
- Walk-forward por temporada; se prueban las temporadas que tienen al menos dos anteriores en la liga.
- M1, M2 y M4 predicen antes de actualizar con el juego. La logística, M3 y M5 se entrenan con las temporadas previas. M6 y las capas aprenden de las predicciones fuera de muestra de las temporadas de prueba anteriores.
- Criterio de la casa: n ≥ 300, mejora, z ≥ 2.0 (error pareado), las dos mitades positivas y calibración ≤ 0.04.
- Totales: los mismos términos de la capa de producción (T* = a + b·T + c·M + d·E + nivel), cambiando T por la vista nueva. O/U a la línea ~promedio, floor(M) + 0.5, con los residuos empíricos.
- Pruebas: 7 ligas × unas 34 comparaciones ≈ 240. Con z ≥ 2 se esperan unos 5 "pasa" por azar, así que cada aprobación se revisó temporada por temporada.

## Resultados del ganador (mejora en milésimas de log-loss contra MEDIA3)
- **LMP** (n 3,354; arranque 467): ninguna vista mejora.
  - Solas: vectores −0.44 (z −0.3), Kalman −1.66, vecinos −3.0, Markov −1.84, boosting −23.2 (z −5.5), apilado −4.9.
  - Como capa: vectores −0.41, Kalman −0.94, vecinos −0.78, Markov −0.53, boosting −2.32.
  - Arranque: todas negativas, de −3 a −19.
- **LVBP** (n 664): vectores +7.26 (z 2.23), vecinos +7.25 (z 2.08) y Markov +7.93 (z 2.53) cumplen el criterio. Pero:
  - MEDIA3 en LVBP queda debajo de la tasa local (−7.84, z −1.71), y el ELO solo le gana a MEDIA3 (+6.51, z 2.29).
  - Contra la tasa local, las tres vistas dan entre −0.6 y +0.1: recuperan el nivel de "siempre gana el local a su tasa" y no agregan información.
  - Lectura: el hallazgo es que MEDIA3 está por debajo de la tasa base en LVBP.
- **MLB** (n 12,781; arranque 851):
  - Temporada completa: nada pasa (vectores +0.58, z 1.17).
  - **Arranque: pasan Kalman** (+12.57, z 3.72; capa +4.2, z 2.52), **vectores** (+10.81, z 3.04; capa +4.05, z 2.30) y el apilado (+9.85, z 2.53).
  - Por temporada (2020, 2021, 2022, 2024, 2025, 2026), Kalman da positivo las 6 en el arranque (+6.4 a +24.0) y vectores también las 6 (+3.4 a +21.5).
- **KBO, NPB, LIDOM, ABL**: nada pasa en temporada completa. En NPB el arranque da positivo (Markov como capa +14.2, z 3.06), pero son 171 juegos, debajo de n 300. LIDOM (447) y ABL (248) son muestra chica.
- **Boosting** empeora sola en todas las ligas, de −1.9 (MLB) a −98 (LIDOM). El patrón es de sobreajuste: la pérdida crece donde hay menos juegos.

## Resultados de totales (mejora de MAE en carreras contra la capa de producción)
- **LMP: vecinos pasa.** MAE 3.519 contra 3.541 (−0.022 carreras, z 3.17, mitades +0.007 / +0.037). O/U a la línea ~promedio +3.22 milésimas (z 2.43).
  - Por temporada: 2016–2021 neutro (−0.022 a +0.056), y **positivo de 2022 a 2025** (+0.077, +0.020, +0.048, +0.024; O/U +3.7, +2.6, +4.2, +1.6).
- **MLB**: el promedio de vistas pasa (MAE −0.003, z 2.35; O/U +0.57, z 2.47). Vecinos (z 2.26) y Markov (z 2.16) pasan en MAE, pero no en O/U. Son mejoras de milésimas de carrera.
- **LVBP, KBO, NPB, LIDOM, ABL**: nada pasa.

## Veredicto
1. **MLB, arranque de temporada (ganador)**: Kalman y vectores pasan, positivos en las 6 temporadas. Candidato a capa de arranque: aplicaría a los primeros 10 juegos de cada equipo y se apagaría después.
2. **LMP, totales**: vecinos pasa, positivo en las últimas 4 temporadas. Candidato a término adicional de la capa de totales de LMP.
3. **LVBP**: ninguna vista nueva agrega información sobre la tasa local. MEDIA3 queda por debajo de esa tasa y el ELO solo le gana a MEDIA3 (z 2.29). Revisar el modelo de producción de LVBP.
4. **Kalman en LMP en el arranque** (lo que se pensaba probar): no pasa (−5.08, z −0.9).
5. Boosting, Markov para el ganador y el apilado de todas las vistas: no pasan en ninguna liga con temporada completa.

Ninguno se aplica sin la aprobación de Alejandro (regla 2).
