# Hipótesis (escrita antes de ver resultados) — 2026-10-09

Forma rápida en fútbol y NFL. Script: `utilidades/minar_forma_rapida.py`. No toca `modelos/` ni `plataforma.py`.

Origen: en la tanda de cualitativos el TMLE marcó rachas que el modelo no ve (fútbol, 5+ derrotas: −8.9 pp;
NFL, 5+ victorias: +9.5 pp). Lectura: el modelo reacciona lento. Se prueba si reaccionar más rápido mejora la predicción
fuera de muestra.

Fútbol (7 ligas juntas; predicción as-of partido por partido, una sola pasada; promedios de liga acumulados as-of):
- Base = el modelo actual: ELO K 20, tasas de goles sin olvido (todo el historial pesa igual), ensamble w 0.4.
- Candidato A: ELO más rápido. K ∈ {20, 30, 40, 60}.
- Candidato B: tasas de goles con olvido por juego del equipo, δ ∈ {1.0, 0.995, 0.99, 0.98, 0.97}
  (δ 0.98 ≈ los últimos 50 juegos pesan la mitad del total).
- Se elige la mejor combinación (K, δ) en el 70 % más antiguo por log-loss 1X2 y se prueba una vez en el 30 %.
- Pasa si en el 30 %: mejora el log-loss 1X2 con z ≥ 1.64 (umbral de fútbol), mejora en las dos mitades y la probabilidad
  de local queda calibrada (|p media − tasa| ≤ 0.04). n ≥ 300.
- Además (no decide): peso del modelo encima del cierre de Pinnacle (ganador local, logit), base contra candidato;
  y residuo del equipo en racha de 5+ derrotas, base contra candidato.

NFL (predicción as-of de `entrenar`; ELO con regresión entre temporadas como en producción):
- Base = lo que usa producción: ELO K 20 más la capa de `plataforma.py` (diferencia de % de victorias de los últimos 5,
  EPA neto por jugada de la temporada con 4+ juegos; sin EPA, diferencial de puntos de la temporada), con los pesos
  reajustados en el 70 % (logística).
- Candidato A: ELO K ∈ {20, 30, 40, 60} con la misma capa reajustada.
- Candidato B: base + media exponencial del margen de puntos (vida media de 2, 3 o 5 juegos), diferencia local − visita.
- Elección en el 70 %, prueba única en el 30 %. Pasa si z ≥ 2.0, dos mitades, calibración ≤ 0.04, n ≥ 300.
- Además (no decide): peso encima del cierre (`nfl_lineas.csv`) y residuo del equipo en racha de 5+ victorias
  contra la base de producción (¿la capa L5 ya lo captura?).

k = 3 pruebas con veredicto (fútbol K y δ juntos, NFL A, NFL B). Falsos positivos esperados por azar ≈ 0.07.

## Resultado (30 % final mirado una vez; k = 3)

Fútbol (11,921 partidos as-of en 7 ligas; prueba desde 2025-04-13, 3,595 partidos):
- Elegido en el 70 %: ELO K 40 y olvido δ 0.98 (antes K 20, sin olvido).
- Prueba: log-loss 1X2 1.00725 → 1.00453, mejora +2.72 milésimas, z +1.82, mitades +1.91 / +3.53, calibración del local
  −0.004. **Pasa** el umbral de fútbol (z ≥ 1.64).
- Over 2.5 con el mismo cambio: +1.86 milésimas, z +1.19, mitades +0.75 / +2.98; calibración −0.030 → −0.013 (no decide).
- Por liga (no decide; cada una con poca muestra): MLS +6.8 (z 1.95), Liga MX +8.5 (z 1.63), Premier +5.8 (z 1.36),
  LaLiga +0.4, Serie A −1.6, Bundesliga −2.1, Ligue 1 −3.4. La mejora viene de MLS, Liga MX y Premier.
- Contra el cierre de Pinnacle: el modelo sigue sin aportar (coeficiente −0.18, z 0.85). Mejor pronóstico, sin ventaja de precio.
- Racha de 5+ derrotas en la prueba (81 casos): el equipo gana 12.1 pp menos de lo que dice la base y 10.1 pp menos de lo que
  dice el elegido. El cambio cierra 2 de 12 pp.
- Pendiente para adoptarlo: correr la validación oficial de los mercados de fútbol con K 40 y δ 0.98 y la aprobación de Alejandro.
  `modelos/futbol.py` no se tocó.

NFL (2,953 partidos as-of; la pasada reproduce exacto a `modelos/americano`; prueba desde 2023-09-17, 886 partidos):
- La capa de producción (L5 + EPA) sobre el ELO solo, en la prueba: +4.95 milésimas, z 1.96.
- A (K): el 70 % elige K 20 (30, 40 y 60 empeoran). K 40 y 60 en la prueba: −0.8 y −1.6 milésimas. **No pasa.**
- B (media exponencial del margen): el 70 % elige vida media 5 (coef. +0.47 por 10 puntos); prueba −0.86 milésimas, z −0.39,
  mitades −3.2 / +1.5. **No pasa.**
- Racha de 5+ victorias en la prueba (99 casos): +5.5 pp sobre el ELO solo, +4.5 pp sobre la base de producción; los dos
  intervalos incluyen el cero. La capa L5 ya cubre parte; lo que queda no se distingue del azar.
- Contra el cierre: el modelo no aporta (coef. −0.06, z −0.45).
