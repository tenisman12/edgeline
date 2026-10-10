# Motor de carreras por equipo en béisbol (10-oct-2026)

Script: `utilidades/motor_carreras.py` · resultados: `trabajo/minar/2026-10-10_motor_carreras_resultados.json`

## Hipótesis (registrada antes de correr)
Un solo modelo del marcador (ataque y defensa de cada equipo con filtro de Kalman, abridor, parque y clima, binomial
negativa) le gana a PRODUCCIÓN en ganador, total, run line y totales por equipo, fuera de muestra, con el protocolo de
siempre (n ≥ 300, z ≥ 2.0, las dos mitades, calibrado).

## Diseño
- log λ = nivel de la liga (promedio con olvido, local y visita) + ataque propio − defensa rival + abridor rival
  (LMP y NPB: carreras que permite contra el promedio de los abridores de su equipo, κ) + parque y clima (`nucleo/parques.py`).
- Ataque y defensa: filtro de Kalman extendido sobre la binomial negativa (ruido q por partido, encogimiento ρ y
  incertidumbre p0 al cambiar de temporada, recentrado diario).
- Hiperparámetros por liga con el 40 % más viejo; la prueba es el 60 % siguiente (LMP desde nov-2019, n 2,373).
- Producción reproducida juego por juego como `validar_mercados.validar_beisbol`: logística media3 cada 30 días, abridores,
  parque y clima, y la capa de totales con los bloques anteriores. Totales por equipo de producción también escalados al
  total de la capa (como plataforma).
- Apilado: cada mes, logística sobre [logit producción, logit motor] con todo lo anterior.
- Dos versiones: v1 (rejilla q ≥ 0.0003, ρ ≥ 0.3, p0 ≥ 0.005) quedó en el borde de la rejilla; v2 amplió la rejilla
  (q 3e-5 a 0.001, ρ 0 a 0.6, p0 0.001 a 0.02) siempre con el 40 % viejo. Se reporta v2; v1 está en la conversación del
  10-oct (ganador peor en todas menos NPB mezcla; totales por equipo ya pasaban en MLB visita, NPB, LMP visita).

## Resultado v2 (z contra producción; "pasa" = z ≥ 2 y las dos mitades a favor)

| Mercado | LMP | MLB | NPB | KBO | LVBP | LIDOM |
|---|---|---|---|---|---|---|
| Ganador, motor | −0.89 | −0.91 | +1.18 | −0.06 | +1.04 | +2.01 pasa (n 475) |
| Ganador, apilado | −1.60 | +1.82 | +0.58 | +0.44 | +1.32 | insuf. |
| Over/Under vs capa | +2.35 (2a mitad −) | +1.21 | +0.71 | −0.60 | −0.04 | insuf. |
| Over/Under apilado vs capa | +2.80 (2a mitad −) | **+2.11 pasa** | +0.39 | −2.36 | insuf. | insuf. |
| Total esperado vs capa (MAE) | **+2.49 pasa** (3.567 → 3.521) | +0.04 | +0.80 | +0.09 | +0.79 | insuf. |
| Run line local −1.5 | −0.19 | +1.82 | +0.87 | −0.51 | +1.72 | +2.72 pasa |
| Total local O/U vs producción escalada | **+3.19 pasa** | **+2.84 pasa** | **+3.42 pasa** | −2.22 | −0.93 | insuf. |
| Total visita O/U vs producción escalada | −0.29 | **+2.78 pasa** | +0.73 | +1.09 | −0.26 | insuf. |

Contra el modelo sin capa, el motor gana claro en totales (LMP O/U z 4.99, MLB 5.30, NPB 4.86).

## Lectura
- Ganador: el motor no mejora a producción (la logística media3 ya junta ELO, box score y carreras). No se toca.
- Totales: la capa de totales de producción ya hace casi todo. En LMP el motor baja el error del total esperado contra la
  capa (pasa), pero el O/U contra la capa falla en la segunda mitad. En MLB el apilado capa + motor pasa (z 2.11).
- Totales por equipo: es donde el motor aporta: LMP local, MLB local y visita, NPB local pasan contra lo que mostraría
  producción. KBO local empeora (KBO corre sin abridores aquí: el archivo de KBO no está en la rama de datos).
- Hiperparámetros en el borde (q 3e-5) en MLB, NPB, KBO: las fuerzas casi no cambian dentro de la temporada.
- Pruebas: 13 mercados × 6 ligas × 2 versiones; con tantas pruebas alguna pasa por azar. Lo que más se sostiene: totales
  por equipo en MLB (n 10,580, las dos) y total esperado de LMP.

## Qué falta para aplicarlo (decide Alejandro)
1. Mostrar el motor en plataforma como dato (carreras por equipo, total del motor) para LMP, MLB y NPB y medirlo en vivo.
2. Si se aprueba: mercado "Total por equipo" con el motor en LMP (local), MLB (los dos) y NPB (local); el total esperado de
   LMP con el motor; MLB O/U con el apilado capa + motor. Ganador sin cambios.
