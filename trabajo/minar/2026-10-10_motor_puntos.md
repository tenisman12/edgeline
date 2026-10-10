# NFL: motor de puntos, lo más preciso que existe y contra el cierre (10-oct-2026)

Script: `utilidades/motor_puntos.py` (núcleo `nucleo/motor_puntos.py`) · resultados: `2026-10-10_motor_puntos_resultados.json`

## Qué dice la literatura (búsqueda del 10-oct)
- Nada público le gana de forma sostenida a la línea de cierre. nfelo la iguala: acierto de ganador 66.6 % (−0.1 pp contra
  el cierre), MAE de margen 10.1 (igual); su ventaja viene de la apertura, no del cierre. Elo de 538: ~51 % ATS.
- Error de la línea de cierre: sd del margen 13.6 puntos; MAE del total de Vegas ~10.6.
- Lo que más pesa: QB titular (un cambio extremo mueve un touchdown), ventaja de local ~2 puntos desde 2022 (menos en
  divisionales), bye +0.3 (no significativo desde 2011; el mercado lo paga ~1), viento arriba de 8–10 mph (unders).
- Mezclar con el mercado: nfelo encoge su modelo hacia la línea (peso fijo ~65 % o variable según el error reciente).
- Fuentes: nfeloapp.com (model performance, market regression, WEPA, home field), arxiv 1211.4000, Frontiers 2024
  (Lopez & Bliss, bye), neilpaine.substack.com (Elo 538), natesilver.net (ELWAY), Sharp Football Analysis (viento).

## Motor
Puntos de cada equipo = nivel local/visita (promedio con olvido) + ataque + QB titular − defensa rival + descanso
+ divisional + viento; Kalman lineal; EPA por partido como segunda observación. Afinado por coordenadas con 2015–2022
(EPA desde 2021, QB desde 2018); prueba 2023-08 a 2026-10 (n ~900). Primera corrida con corte al 40 % (2019-11): el afinado
no tenía EPA ni casi QB; resultados parecidos (ganador vs producción z 1.54, O/U z 2.06 con calibración +0.047).
Elegido: q 0.25, ρ 0.45, p0 2, EPA 0 (no mejora), QB nuevo 0, divisional 1 punto, viento 0.6 por mph arriba de 10,
bye y semana corta 0. sd margen 13.0, sd total 13.8.

## Resultado (prueba 2023–2026)

| | n | z | Lectura |
|---|---|---|---|
| Ganador, motor vs producción | 919 | +1.65 | mejor, no llega |
| Margen esperado vs producción (MAE 10.61 → 10.46) | 897 | +1.48 | mejor, no llega |
| Total esperado vs producción (MAE 10.76 → 10.56) | 913 | +1.41 | mejor, no llega |
| Over/Under vs producción | 913 | +1.73 | mejor, no llega |
| Moneyline vs cierre | 919 | −4.13 | el cierre gana |
| Moneyline apilado con el cierre | 919 | −0.24 | no suma |
| Spread vs cierre | 897 | −3.33 | el cierre gana |
| Spread apilado | 897 | −1.50 | no suma |
| Total vs cierre | 913 | −2.79 | el cierre gana |
| Total apilado | 913 | −1.04 | no suma |
| MAE margen: cierre 10.04, motor 10.46; total: cierre 10.24, motor 10.56 | | | |

En el apilado el coeficiente del motor sale negativo en moneyline (−0.33) y total (−0.20): cuando el motor se aleja del
cierre, el cierre acierta.

## Peso del modelo en la decisión (decidir_v2)
Mezcla p = w·modelo + (1−w)·cierre en logit, prueba 2023–2026, contra el cierre solo:

| w | Moneyline (producción) | Spread | Total |
|---|---|---|---|
| 0.10 | z −1.13 | −1.14 | −0.69 |
| 0.25 | −1.67 | −1.68 | −1.24 |
| 0.50 (el de producción) | **−2.59** | **−2.57** | **−2.13** |

APLICADO (aprobado el 10-oct): `decidir_v2.PESO_MODELO["nfl"]` 0.5 → 0.0. La probabilidad final de la NFL es la de
Pinnacle; los picks salen solo de precio (Pinnacle contra la mejor casa), que es lo que sharp.py midió que paga.

## Contexto
El motor se muestra en cada partido de NFL (puntos por equipo, margen, total y valor del QB titular), sin peso.
