# Hipótesis (escrita antes de ver resultados) — 2026-10-09: capa de totales

Pedido (Alejandro, 9-oct): "quiero los totales ya totalmente validados y listos" y picks de totales.
Estado al 8-oct (`salida/validacion_mercados.json`): el total del modelo no le gana a la base en NHL, NBA, NFL, MLB, NPB y KBO
(Total esperado z −2.23 a 0.71; Over/Under z −2.72 a 1.0). En béisbol el over sale cargado abajo (p media 0.434–0.453 contra
0.475–0.488 real) y en NHL arriba (0.429 contra 0.416): la media se acerca, la forma de la distribución falla.

Script: `utilidades/minar_capa_totales.py`. Corre el MISMO walk-forward de `utilidades/validar_mercados.py` (entrena solo con lo
anterior a cada bloque de 30 días) pero empezando 48 meses atrás. Los primeros 24 meses solo sirven para que la capa tenga
predicciones previas con qué ajustarse; se califican los últimos 24 meses, igual que la validación oficial, contra la MISMA base
(promedio y frecuencia de over de todo lo anterior).

La capa se ajusta en cada bloque solo con las predicciones de bloques anteriores (mínimo 300):
- **C1 total encogido**: T* = a + b·T_modelo + c·M, con M = media de totales de la liga con olvido (vida media de 400 juegos,
  hasta el día anterior). Mínimos cuadrados. Esperado: b entre 0 y 1 (el modelo exagera las diferencias) y MAE menor que la base.
- **C2 over/under con residuos empíricos**: p(over L) = fracción de los últimos 3,000 residuos previos r (real − T*) con T* + r > L.
  Esperado: calibración ≤ 0.04 y Brier menor que la base.
- **C3 recalibración logística** del p_over del modelo: logit q = a + b·logit p (ajuste en lo previo). Esperado: mejora a la base.
- Fútbol (over 1.5 / 2.5 / 3.5 por liga): C1 sobre goles totales y C2 con los residuos; C3 sobre el p_over del modelo.

Pasa con el criterio oficial: n ≥ 300, mejora a la base, z ≥ 2.0 (fútbol 1.64), mejora en las dos mitades, calibración
|p media − tasa| ≤ 0.04 (probabilidades) o |sesgo| ≤ 0.10 desviaciones (totales).
k = número de pruebas con resultado; falsos "pasa" esperados ≈ k × 0.023.
Lo que pase entra en `validar_mercados.py` (validación oficial) y en `plataforma.py` con los coeficientes de toda la muestra.
"Publicable" sigue queriendo decir que le gana a la tasa histórica, no a la casa: contra la línea real se mide en vivo.

Agregadas después de ver C1–C3 en NHL, NBA, NFL, NCAAMB y fútbol (cuentan en k igual que las demás):
- **C4 total con ritmo**: T* = a + b·T_modelo + c·M + d·E, con E = ritmo de los dos equipos (media con olvido del total de sus
  juegos, vida media 20 juegos, encogida a M con 5 juegos de peso; hasta el bloque anterior). Esperado: d > 0 y MAE menor que la base.
- **C5 over/under de C4**: como C2, con los residuos de C4.

Agregadas después de ver la validación oficial de LMP (Over/Under (capa) p media 0.446 contra 0.497: falla la calibración
por 1.1 pp; la capa usa residuos de varias temporadas y la anotación cambió). Se prueban en TODAS las ligas y cuentan en k:
- **C6 nivel reciente**: T* de C4 + media de los últimos 300 residuos previos.
- **C7 over/under de C6**: residuos del último año previo (mínimo 300), centrados en ese nivel.

## Resultado del minado (últimos 24 meses calificados; k = 161 pruebas con resultado, falsos "pasa" esperados ≈ 3.7)
Archivo: `2026-10-09_capa_totales_resultados.json`. Over/under con la capa (C5 / C7), z:
- Pasan con margen: NCAAMB 24.4 / 25.3, NBA 10.9 / 10.2, MLB 5.5 / 5.4, LMP 4.9 / 5.3 (C7 corrige la calibración:
  0.479 contra 0.485), NPB 3.4 / 3.4, Bundesliga over 2.5 2.5 / 3.2 y over 3.5 3.5 / 3.6, LaLiga (ya pasaba sin capa).
- NFL: C7 z 2.50 y calibración 0.483 contra 0.498 (C5 fallaba la calibración).
- No pasan: NHL (z −0.2 a −0.3: el total del modelo no se separa de la base), KBO, Premier, Serie A, Ligue 1, Liga MX.
- MLS over 2.5: C5 2.35, C7 1.42.
Se adopta C6 + C7 (nivel reciente y residuos del último año) en `nucleo/capa_totales.py` y en la validación oficial.

## Validación oficial (`utilidades/validar_mercados.py`, datos al 8-oct, 24 meses + 24 de precalentamiento)
"Over/Under (capa)": NCAAMB z 34.6, NBA 9.7, NCAAFB 5.5, LMP 5.0, MLB 4.8, NPB 3.5, NFL 3.0 -> publicable.
NHL z 0.2 y KBO −0.7 -> sin_validar (siguen con el total del modelo).
Revisión por época: la capa de NBA en octubre-noviembre subestima 6.4 puntos y es peor que la base (629 juegos; el ritmo
viene de los playoffs). En producción la capa de NBA espera a que los dos equipos lleven 15 juegos de la temporada
(`MIN_TEMPORADA`). Béisbol (LMP en octubre: mejora el MAE), NCAAMB y NFL al inicio de temporada no muestran ese problema.
