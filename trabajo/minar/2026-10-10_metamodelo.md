# Metamodelo apilado (como razona un tipster): 2026-10-10

Script: `utilidades/metamodelo.py` (núcleo en `nucleo/metamodelo.py`, filas en `utilidades/gen_filas_metamodelo.py`).
No toca modelos ni picks.

## Qué es
Una sola probabilidad por lado, con las capas en el orden de un tipster:

    logit(q) = b0 + b1*logit(Pinnacle sin vig al decidir) + b2*(logit(modelo) - logit(Pinnacle))
               + sum(c_i * ángulo_i) + sum(d_j * público_j) [+ e*empate]

Logística con castigo L2 por grupo: mercado y modelo casi libres, ángulos (200) y público (400) encogidos hacia 0.
Walk-forward: cada bloque (30 días fútbol, 60 NFL) se predice con un ajuste hecho solo con partidos anteriores.
En 1X2 las tres probabilidades se normalizan.

## Datos con historia de precios
- Fútbol 7 ligas (football-data): Pinnacle temprana (se decide ahí) y cierre (CLV), mejor precio del mercado, Bet365.
  1X2: 4,423 partidos fuera de muestra (2023-05-28 a 2026-01-14). O/U 2.5: 4,371.
- NFL: moneyline de cierre (nflverse), 1,526 partidos fuera de muestra (2020-11 a 2026-10). Sin temprana: prueba contra el cierre.
- Béisbol, NHL, NBA, tenis: sin historia de cuotas (las fotos de The Odds API empiezan el 1-oct-2026). No se pueden medir todavía.
- Público (Action Network): 51 lados en 2026 con modelo, mercado y público a la vez. Muestra corta: solo descriptivo.

## Resultado: log-loss por partido contra el mercado al decidir (milésimas; positivo = mejor)
Fútbol 1X2 (cierre de Pinnacle como techo: +2.17, z 2.07)
- 1 mercado recalibrado: +1.48 (z 2.45; mitades +2.51 / +0.45)
- 2 + modelo: +1.66 (z 2.61; mitades +2.51 / +0.81)
- 3 + ángulos (completo): +1.56 (z 2.34; mitades +2.36 / +0.76)
- Modelo solo: −20.1 (z −8.75)
- Pesos del último ajuste: mercado 1.09, modelo −0.15, empate +0.11; ángulos entre −0.06 y +0.03.

Fútbol O/U 2.5 (cierre: +3.46, z 3.88)
- Mercado recalibrado: 0.00. + modelo: −0.22 (z −0.29). Modelo solo: −6.1 (z −3.25).

NFL ganador (contra el cierre)
- Mercado recalibrado: −0.54 (z −2.13). + modelo: −0.41. + ángulos: −0.58. Modelo solo: −30.1 (z −5.54).

## Apuestas a 1 u (cuota ≥ 1.80, EV del metamodelo ≥ 4 %, una por partido)
Fútbol 1X2
- Precio de Pinnacle temprana: 9 apuestas (casi nunca hay EV contra su propio precio).
- Mejor precio del mercado: 1,177 apuestas, acierto 29.8 %, cuota media 4.18, +38.8 u, ROI +3.3 % (z 0.68),
  CLV +3.89 % (z 13.97), mitades +25.6 / +13.2.
- Bet365: 132 apuestas, acierto 31.1 %, cuota 3.71, +18.2 u, ROI +13.8 % (z 0.82), CLV +0.28 % (z 0.48).
- Comparación: EV del modelo solo al mejor precio, 3,665 apuestas, −496.8 u, ROI −13.6 %, CLV −0.62 %.
Fútbol O/U 2.5: 43 apuestas al mejor precio, −0.8 u (CLV +6.96 %). Bet365: 4.
NFL al cierre: 72 apuestas, −24.2 u (ROI −33.6 %).

## Público 2026 (51 lados, MLB, NCAAF, NFL, NHL)
- Público cargado (≥ 60 % de boletos): 35 lados, ganó 65.7 % con mercado 62.6 % y modelo 63.4 %.
- Contra el público (≤ 40 %): 9 lados, 44.4 % con mercado 42.8 %.
- Dinero 10 pp arriba de los boletos: 4 lados, 75 % con mercado 48.3 %.
- Peso ajustado del público: 0.001 (con el castigo, sin datos suficientes queda en 0).

## Lectura
- Lo que mejora la probabilidad en fútbol viene casi todo de recalibrar el precio temprano de Pinnacle (favoritos y empate
  un poco subvaluados); con eso el metamodelo llega cerca del cierre. El modelo agrega +0.18 milésimas y los ángulos −0.10.
- El peso del modelo sale negativo (−0.15): cuando el modelo discrepa de Pinnacle, Pinnacle suele tener razón y el modelo
  exagera. Por eso el EV del modelo solo pierde en todos los mercados.
- Ganancia: solo aparece al mejor precio del mercado (CLV +3.9 % con z 14, ROI +3.3 % con z 0.7). En Bet365 la muestra es chica
  (132) y el CLV es +0.3 %. La parte que sí está demostrada es el CLV al mejor precio.
- NFL al cierre: el mercado no se le gana con modelo ni ángulos.
- Siguiente paso: el mismo metamodelo en vivo para béisbol, NHL y NBA con las fotos de Pinnacle de 2026 y el público, para
  que se ajuste en cuanto haya ~1,000 partidos por deporte.
