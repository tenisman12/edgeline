# Hipótesis (escrita antes de ver resultados) — 2026-10-08

Ángulos situacionales, tanda 1: calendario y desgaste. Catálogo y códigos en el doc "Ángulos situacionales".
Script: `utilidades/minar_situacionales.py`.

## Método único (sustituye al residuo por subgrupo del 8-oct y al log-loss de 3 temporadas del 6-oct)

- Base: probabilidad del modelo as-of, partido por partido, sin ver el futuro.
  - NHL, NBA, NCAA básquet, NFL, NCAAF: la lista `cal` de `entrenar()` (la misma que usa el Platt de producción),
    con cada predicción emparejada a su partido. NHL ya trae el factor de segunda noche del modelo.
  - Béisbol (MLB, NPB, KBO, LMP, LVBP, LIDOM, ABL): `entrenar_logistica` ajustada con el 35% más antiguo para
    predecir el tramo 35–70%, y con el 70% más antiguo para predecir el 30% final. Los features de cada fila ya son as-of.
  - Fútbol (7 ligas): `futbol.entrenar` reentrenado por bloques de 30 días solo con lo anterior; p = local gana.
- Partición: 70% más antiguo por fecha (explorar y ajustar), 30% más reciente (prueba, se mira una vez).
- Ajuste en el 70%: base = logística de una variable sobre logit(p) (recalibra el modelo); con ángulo =
  la misma + β·x. x está firmado hacia el local (+ = favorece al local).
- Métrica: log-loss por partido en el 30%, diferencia pareada base − ángulo (positivo = el ángulo mejora).
- Pasa si: β tiene la dirección registrada abajo, z ≥ 2.0 en el 30%, mejora en las dos mitades del 30%,
  calibración |p media − tasa real| ≤ 0.04 en los partidos donde el ángulo está activo, y n activo ≥ 300 en el 30%.
  Con menos de 300 activos: "muestra insuficiente".
- Contra el mercado (paso 7): en NFL (`mercado/nfl_lineas.csv`) y fútbol (`mercado/futbol_cuotas.csv`, Pinnacle al cierre)
  se repite todo con la probabilidad sin vig del cierre como base.
- k = número total de pruebas ángulo × liga. Falsos pasa esperados por azar ≈ k × 0.023 (una cola).

## Ángulos y dirección esperada (x firmado hacia el local)

Hockey (NHL)
- H1 visita en segunda noche, local descansado: x = 1. Esperado β > 0.
- H2 local en segunda noche, visita descansada: x = 1. Esperado β < 0.
- H4 un día de diferencia de descanso: x = signo(días local − días visita) cuando la diferencia es 1. Esperado β > 0.
- H6 tercer juego en 4 noches: x = 1[visita] − 1[local]. Esperado β > 0.
- H7 carga de 7 días: x = juegos de la visita − juegos del local en los 7 días previos. Esperado β > 0.
- H8 regreso de pausa de 7 días o más: x = 1[local] − 1[visita]. Esperado β < 0 (óxido).
- H13 gira larga: x = número de juegos seguidos de visita del visitante, menos 1, tope 5. Esperado β > 0.
- H14 regreso a casa tras gira de 3 o más: x = 1. Esperado β < 0.
- H15 último juego de gira del visitante (su siguiente juego es de local, gira de 3 o más): x = 1. Esperado β < 0.
- H16 ida y vuelta, revancha inmediata: x = +1 si el local perdió el juego anterior entre los dos (≤ 3 días), −1 si lo perdió la visita. Esperado β > 0.
- H17 tras prórroga o shootout: x = 1[visita] − 1[local]. Esperado β > 0.
- H18 partido anterior físico: x = (minutos de castigo previos visita − local) / 10. Esperado β > 0.
- H19 portero suplente en segunda noche: x = 1[visita en 2.ª noche con suplente] − 1[local ídem]; suplente = no es el de más aperturas en los últimos 10 juegos del equipo. Esperado β > 0.
- H20 carga del portero: x = (aperturas seguidas del portero visitante − local) / 10, tope 10. Esperado β > 0.
- H21 tras perder por 4 o más: x = 1[local] − 1[visita]. Esperado β > 0.
- H22 tras perder en prórroga o shootout: x = 1[local] − 1[visita]. Esperado β > 0.

Béisbol (todas las ligas juntas y MLB sola)
- B1 día tras noche (primer lanzamiento antes de 17:00 tras uno de 17:00 o más ayer): x = 1[visita] − 1[local]. Esperado β > 0. Sin KBO ni NPB (no hay hora).
- B2 primer juego tras día libre: x = 1[local] − 1[visita]. Esperado β > 0.
- B5 días seguidos jugando: x = (racha visita − racha local) / 10, tope 20. Esperado β > 0.
- B10 primer juego de serie: x = 1. Esperado β > 0.
- B11 último juego de serie (getaway): x = 1. Esperado β > 0.
- B12 evitar la barrida (perdió todos los juegos previos de la serie, 2 o más): x = 1[local] − 1[visita]. Esperado β > 0.
- B13 gira larga: x = (juegos seguidos de visita del visitante − 1) / 10, tope 12. Esperado β > 0.
- B14 regreso a casa tras gira de 6 o más: x = 1. Esperado β < 0.
- B15 tras extra innings (pitcheo del equipo ≥ 10 entradas): x = 1[visita] − 1[local]. Esperado β > 0.
- B18 abridor corto (promedio < 3 entradas en sus 3 aperturas previas): x = 1[visita] − 1[local]. Esperado β > 0. Solo LMP y NPB (únicos con bitácora histórica de lanzadores).
- B19 abridor con 4 días de descanso o menos: x = 1[visita] − 1[local]. Esperado β > 0. Solo LMP y NPB.
- B21 tras perder por 7 o más: x = 1[local] − 1[visita]. Esperado β > 0.

Básquet (NBA y NCAA básquet)
- K1 segunda noche: x = 1[visita] − 1[local]. Esperado β > 0. (Ya medido el 6-oct sin efecto en NBA; se repite con el método único.)
- K2 tercer juego en 4 noches: x = 1[visita] − 1[local]. Esperado β > 0.
- K3 diferencia de descanso: x = días local − días visita, tope ±2. Esperado β > 0.
- K4 descanso de 4 días o más: x = 1[local] − 1[visita]. Esperado β > 0.
- K8a gira larga: x = juegos seguidos de visita del visitante − 1, tope 5. Esperado β > 0.
- K8b regreso a casa tras gira de 3 o más: x = 1. Esperado β < 0.
- K10 tras perder por 20 o más: x = 1[local] − 1[visita]. Esperado β > 0.
- K11 tras prórroga (solo NBA, minutos > 240): x = 1[visita] − 1[local]. Esperado β > 0.

NFL y NCAAF
- N4 tras jugar lunes: x = 1[visita] − 1[local]. Esperado β > 0. Solo NFL.
- N5 sale de semana libre contra rival en semana corta: x = +1 local descansado / −1 visita descansada. Esperado β > 0.
- N8 segundo juego seguido de visita: x = 1. Esperado β > 0.
- N12 tras perder por 20 o más: x = 1[local] − 1[visita]. Esperado β > 0.
- N13 tras ganar en tiempo extra (solo NFL): x = 1[visita] − 1[local]. Esperado β > 0.

Fútbol (7 ligas juntas; Champions agregada al calendario cuando el nombre del equipo cuadra)
- F1 diferencia de descanso: x = (días local − días visita) / 3, tope ±3. Esperado β > 0.
- F13 tras perder por 3 o más: x = 1[local] − 1[visita]. Esperado β > 0.

## Resultado (30 % final mirado una vez; k = 70 pruebas ángulo × liga × base)

Veredicto: **ninguno pasa**. 44 no pasan y 26 tienen muestra insuficiente (menos de 300 casos activos en la prueba).
65 de las 70 llegaron a calcular z; falsos "pasa" esperados por azar ≈ 1.5; salieron 0. Detalle por prueba en `2026-10-08_situacionales_tanda1_resultados.json`.

Método unificado, segunda noche NHL (10,473 predicciones as-of; prueba 3,142 partidos desde el 2024-03-21):
- H1 visita en segunda noche: β +0.141 (+3.5 pp, la misma magnitud que el residuo por subgrupo), z +1.29,
  las dos mitades positivas, 459 activos. No pasa: la dirección se sostiene pero sin significancia fuera de muestra.
  El "z +2.66" del 8-oct era sobre toda la muestra, sin partición; se retira.
- H2 local en segunda noche: 161 activos. Muestra insuficiente.
- H4 un día de diferencia: z +1.23. No pasa.

Lo más cercano (dirección registrada, mejora en las dos mitades, z < 2): H7 carga de 7 días NHL (z +1.78),
NCAA básquet K8a gira larga (z +1.95, pero una mitad negativa), NFL N13 tras ganar en tiempo extra (z +1.89, 41 activos).
Contra la dirección registrada: H17 tras prórroga NHL (β −4.2 pp: el equipo que viene de prórroga rinde mejor, z −1.81),
H14 regreso a casa NHL (β +1.3 pp, z +1.84).
Contra el cierre (NFL y fútbol): nada se acerca.

Notas de datos:
- B1 día tras noche: casi siempre lo viven los dos equipos de la misma serie y se cancela; solo 28 casos asimétricos.
- N5 bye contra semana corta: el calendario de la NFL casi no lo produce (0 casos).
- B18/B19 abridor corto o con poco descanso: solo LMP y NPB tienen bitácora histórica; 56 y 16 activos.
- MLB tiene bitácora de lanzadores solo desde 2026-08-08: bullpen y abridor por descanso no se pueden medir todavía.
