# Motor de goles por equipo en hockey (10-oct-2026)

Script: `utilidades/motor_goles.py` (núcleo: `nucleo/motor_goles.py`) · resultados: `2026-10-10_motor_goles_resultados.json`

## Hipótesis (registrada antes de correr)
El motor (ataque, defensa y portero titular con Kalman, xG como segunda observación, segunda noche, goles de tiempo
regular con binomial negativa y prórroga aparte) le gana a producción en ganador, total, puck line, empate a 60 min o
goles por equipo (n ≥ 300, z ≥ 2.0, las dos mitades, calibrado).

## Diseño
Producción reproducida como plataforma: `modelos/hockey.entrenar` cada 30 días con lo anterior, `predecir` con fecha,
segunda noche real y GSAx del portero titular (NHL), y la capa de totales. Motor afinado con el 40 % más viejo de cada liga
(rejilla: q, ρ, p0, peso del xG, portero, segunda noche). DEL (749) y SHL (412) no llegan a 800 juegos.

## Resultado (z contra producción)

| Mercado | NHL (n 6,340) | AHL (n 1,402) | Liiga (n 625) |
|---|---|---|---|
| Ganador | +0.01 | −0.58 | −1.70 |
| Ganador apilado | +0.90 | −1.00 | +0.29 |
| Over/Under | −0.10 | −0.85 | +1.32 |
| Over/Under apilado | +1.72 | −0.05 | +1.75 |
| Puck line local −1.5 | −1.10 | +1.18 | −0.86 |
| Empate a 60 min | −0.96 | −4.93 | −3.05 |
| Goles local O/U | −1.84 | −0.57 | −0.24 |
| Goles visita O/U | +1.39 | −0.47 | +1.27 |
| Total esperado (MAE) | −1.61 | −0.00 | +1.27 |

Nada pasa. El afinado no eligió el xG ni el portero (wx 0, portero 0) en ninguna liga: con goles reales el filtro no
saca más de ahí; producción ya trae xG (NHL 0.75) y GSAx.

## Empate a 60 minutos
Modelo y motor subestiman el empate (cal −0.06; ~16 % contra 22–25 % real). Con un ajuste por liga sobre el motor, contra
la tasa histórica de la liga: Liiga z 0.05, AHL z 0.29, NHL peor. Ninguno le gana a la tasa.
APLICADO (aprobación del 10-oct): en plataforma el empate a 60 min = tasa de la liga (últimos 1,500 juegos con dato:
NHL 24.6 %, AHL 21.9 %, Liiga 22.0 %, SHL 19.2 %, DEL 18.4 %); local y visita conservan la proporción del modelo.
Importa en la AHL, donde las casas europeas solo cotizan el 1X2 a 60 minutos.

## Conclusión
El motor de goles no se aplica: producción (xG + GSAx + segunda noche) ya es mejor o igual. Queda el script para volver a
medir cuando haya más temporadas de SHL y DEL.
