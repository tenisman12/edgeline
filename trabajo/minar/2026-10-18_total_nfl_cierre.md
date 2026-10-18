# NFL Total contra la línea de cierre (18-oct-2026)

**Disparador.** `revision.py` (corrida 2026-10-18 22:12Z) marcó en rojo: NFL Total prometió 59.3 % y acertó 41.0 % en
39 casos (z −2.32). En vivo: 39 partidos únicos del 4 al 18 de octubre; overs 23 (acierto 47.8 %), unders 16 (31.2 %).

**Por qué la validación lo daba como publicable.** `validar_mercados.py` compara contra la tasa histórica (regla 4 de
CLAUDE.md). La apuesta se hace contra la línea de la casa, y esa comparación no estaba hecha para el modelo de producción.

**Hipótesis y criterio (antes de correr).** Si hay ventaja contra el cierre: el lado elegido acierta más de 50 % con
z ≥ 2, y el p_over le gana en log loss a p = 0.5 con z ≥ 2 y en las dos mitades.

**Medición** (`utilidades/medir_total_nfl_cierre.py`, producción reproducida as-of, `total_line` de
`datos/mercado/nfl_lineas.csv`):

- 2018–2026, n 2,281: acierta el lado 49.8 % (z −0.19). Promete 58.9 % al lado elegido. Su total difiere de la línea
  3.19 puntos en promedio. Log loss −29.6 milésimas contra p = 0.5 (z −5.91; mitades −24.0 y −35.2).
- 2023–2026, n 927: 49.3 % (z −0.43); −33.7 milésimas (z −4.14).
- Por temporada, el lado acertado va de 43.5 % (2026, n 108) a 53.8 % (2019, n 266). Ninguna temporada mejora a p = 0.5.

Coincide con `2026-10-10_motor_puntos.md`: producción contra el cierre en el total, Brier 0.2649 contra 0.2500.

**Veredicto: no pasa.** El total esperado del modelo no ubica el lado de la línea mejor que una moneda, y su
probabilidad está inflada unos 9 puntos.

**Aplicado.**
1. `plataforma.CONTRA_CIERRE_NO = {("nfl", "Total")}`: el mercado queda `sin_validar` aunque el validador lo apruebe.
   `decidir_v2` le da peso 0 al modelo (p final = mercado), así que no genera pick. La lectura (total esperado, lado,
   p_over) se sigue publicando completa.
2. `revision.py`: entrada en CONOCIDOS hasta 2026-12-31, con su motivo.

**Pendiente (decisión de Alejandro).** Dejar el total de NFL solo como lectura o rehacer el modelo del total (el motor
de puntos tampoco le gana al cierre: −17.1 milésimas, z −2.79; apilado −2.0, z −1.04).
