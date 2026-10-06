# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Deporte/liga: NHL. Mercado: Over/Under de goles en las líneas 5.5 y 6.5.
Problema medido: el O/U del modelo está descalibrado (p media 0.431 vs tasa real 0.415) y no supera a la base.
Señal: la DISTRIBUCIÓN del total, no el promedio. El modelo usa Poisson(mu) con mu = goles esperados
(xG 75 %, GSAx del portero, total encogido). Hipótesis: P(total > L) dado mu tiene otra forma (goles en
arco vacío, efectos de marcador, sobre/infradispersión), y calibrarla as-of mejora el O/U.
Variantes (k = 3):
  B) binomial negativa con dispersión estimada en el tramo de exploración;
  C) recalibración logística: logit p = a + b·logit(p_poisson) + c·[L = 6.5];
  D) logística directa sobre (mu − L) y [L = 6.5].
Dirección esperada: menos log-loss que Poisson y que la tasa base histórica de over en esa línea.
Métrica: log-loss por partido-línea; error pareado contra el modelo actual (A) y contra la base.
Partición: 70 % más antiguo (ajuste) / 30 % más reciente (prueba, se mira una vez).
Criterio: n >= 300 en prueba, z >= 2.0, mejora en las dos mitades de la prueba, |p media − tasa| <= 0.04.
Contra el mercado: no hay cuotas históricas de totales NHL; solo se puede decir si supera a la base.

## Resultado (prueba 30 %, 2,160 partido-línea desde 2025-11-24; mirado una vez)
- A Poisson actual (con GSAx): vs base +2.06 milésimas, z 1.48, mitades +1.24 / +2.88. p media 0.507 vs real 0.518.
- B binomial negativa (r=12): vs base +0.30, z 0.26; peor que Poisson (−1.75).
- C recalibración logística: vs base +1.76, z 1.97; mitades +0.33 / +3.20.
- D logística sobre (mu − L): vs base +1.80, z 1.99; mitades +0.34 / +3.27.
Veredicto: NO PASA (ninguna llega a z 2.0). k = 3 variantes. La forma Poisson no es el problema:
recalibrarla no mejora al modelo actual. El total de NHL se queda como contexto.
