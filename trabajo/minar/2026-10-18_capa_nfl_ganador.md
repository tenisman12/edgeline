# NFL Ganador: la capa L5 + EPA inflaba la probabilidad (18-oct-2026)

**Disparador.** `revision.py` (corrida 2026-10-18 23:35Z): NFL Ganador prometió 68.0 % y acertó 52.5 % en 40 partidos
(z −2.09). En esos 40 el mercado le daba 59.1 % al mismo lado; el modelo iba 8.9 puntos arriba del mercado en promedio.

**Causa.** La validación oficial mide `americano.entrenar` sin capa (publicable, skill +11.4 %, n 557). Producción le suma
en logit la capa L5 + EPA (`plataforma._ajuste_capas_nfl`, pesos 0.93 y 0.187) encima de la p ya calibrada con Platt.
Esos pesos salieron de `pesos_capas_v2` sobre el ELO crudo (n 808), antes de Platt. Es la regla 2 del diagnóstico
maestro: un componente medido solo no se suma a un modelo ya calibrado sin volver a medir el conjunto.

**Hipótesis y criterio (antes de correr).** La capa sirve si mejora el log loss con z ≥ 2 en las dos mitades y queda
calibrada (|promete − acierta| ≤ 4 % en el favorito).

**Medición** (`utilidades/medir_capa_nfl_ganador.py`, walk-forward por bloques de 30 días, 2019-09 a 2026-10, n 2,039):

- Sin capa: promete 64.3 %, acierta 63.6 % (z −0.66), log loss 0.6432.
- Con capa: promete 70.6 %, acierta 64.8 % (z −6.00), log loss 0.6521.
- La capa contra sin capa: −8.9 milésimas (z −1.59; mitades −18.2 y +0.4).
- Por banda con capa: 0.6–0.7 promete 65.0 y acierta 59.3 (z −2.73); 0.7–0.8 promete 74.6 y acierta 67.7 (z −3.42);
  0.8+ promete 87.5 y acierta 76.9 (z −7.51, n 541).

**Veredicto: no pasa.**

**Aplicado.** `plataforma.CAPA_NFL_ACTIVA = False`. La p del ganador de NFL vuelve a ser la del modelo validado. La capa
se sigue calculando y se publica como contexto en `modelo.capas_medidas` (con `p_con_capa`). `decidir_v2` no la cuenta como
duda. `revision.py`: NFL Ganador en CONOCIDOS hasta el 30-nov-2026, porque las 40 filas en vivo ya registradas tienen la p
con capa; `descalibrados()` bloquea el pick mientras tanto.

**Candidato (decisión de Alejandro).** La capa con su peso reajustado por temporada (logit p = logit p0 + c·capa, c elegido
con las temporadas anteriores, entre 0.20 y 0.35) mejora +3.0 milésimas fuera de muestra (n 1,536, z 2.06; mitades +0.08 y
+5.92). Pasa el protocolo por muy poco y la primera mitad es prácticamente cero. Se activaría con un peso de 0.25 en lugar
de 1.0.
