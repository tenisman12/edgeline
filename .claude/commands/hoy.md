---
description: Lectura completa de los partidos del día y decisión por partido (Picks IA en sesión, sin API)
argument-hint: "[AAAA-MM-DD] [ligas separadas por coma]"
---

Argumentos: $ARGUMENTS  (fecha opcional; ligas opcionales. Sin fecha = hoy en CDMX; sin ligas = todas.)

Sigue `CLAUDE.md` y el criterio de `ia/instrucciones_picks.md`. Ningún número se inventa.

## 1. Datos frescos
```bash
git pull -q 2>/dev/null; git log -1 --format='%ci %s'
python utilidades/volcar_partidos.py --indice --fecha <fecha> --ligas <ligas>
```
(`<fecha>` y `<ligas>` salen de $ARGUMENTS; si no vienen, omite esas opciones.) Reporta en una línea: hora de `proximos.json`,
último snapshot de cuotas (`salida/odds_snapshots_2026.csv`, columna `ts_utc`) y si algo tiene más de 12 h.

## 2. Volcar y leer TODO
```bash
python utilidades/volcar_partidos.py --fecha <fecha> --ligas <ligas>
```
Lee cada archivo de `trabajo/volcado/` completo. Si son muchas ligas, lanza un subagente por liga con estas mismas
instrucciones y que te devuelva las lecturas en JSON; tú revisas y unificas.
Por partido usa todos los bloques: contexto, modelo (+derivados), validacion, alerta, cuotas, mercados, valor,
movimiento (con serie), lectura sharp vs público de `salida/mercado_publico.json` (por partido), consenso, forma (ventanas, ELO, power, status, osciladores, ou4), h2h_datos,
estadisticas_equipo, jugadores_clave, picks/pick_top (puntaje Pick Premium) y bloques (qué falta).

   3. Osciladores y forma: osciladores, L10 y L5, splits local/visita, estadísticas de equipo relevantes, H2H y O/U
      recientes. Si la forma es de la temporada pasada o hay menos de 5 juegos, decirlo.
   4. Mercado: probabilidad sin vig (casa y sharp), movimiento desde la apertura, lectura sharp vs público y predictor ESPN.
   5. Relación entre capas: conteo de señales a favor y en contra, con el número de cada una.
   6. Decisión final y por qué: nivel, mercado, cuota y la regla que la define (validación, EV, cuota 1.70-3.00).
      Si es PASAR, cuál es la mejor lectura y qué le falta para ser pick.
Sin adjetivos ni juicios de valor cuando se pida. Partidos ya empezados: marcarlos y dejarlos al final.
Sin stakes en pesos. Cierra con "Fuentes:" si usaste internet.
No hagas commit de `salida/picks_ia.json` ni `historial_ia.csv` al repo público sin que el dueño lo pida.

## 4. Análisis por partido (en este orden)
1. Contexto  2. Modelo (con estado de validación y sesgos)  3. Osciladores y forma  4. Mercado (prob. sin vig,
movimiento, predictor ESPN)  5. Relación entre capas con números  6. Decisión: PREMIUM | PICK | LEAN | REVISAR | PASAR.
Conteo de señales independientes a favor y en contra, todas con el mismo peso. Edge >15% = "revisar".

## 5. Guardar en el formato común
Escribe `trabajo/lecturas_<fecha>.json` (lista, formato de `ia/instrucciones_picks.md`) con TODOS los partidos leídos,
incluidos los PASAR. Luego:
```bash
python utilidades/guardar_lecturas.py trabajo/lecturas_<fecha>.json --probar
python utilidades/guardar_lecturas.py trabajo/lecturas_<fecha>.json --origen claude-code
```
Corrige cualquier ERROR que marque el validador y vuelve a correr.

## 6. Respuesta (formato obligatorio)
Nunca entregar solo la tabla. Siempre las dos partes:

A. Resumen: tabla con TODOS los partidos leídos: hora CDMX, partido, decisión (PREMIUM | PICK | LEAN | REVISAR | PASAR),
   mercado, lado y cuota. Un pick por partido: si la decisión es PASAR, poner la mejor lectura marcada "sin valor".

B. Análisis por partido, uno por uno, en prosa y con números, siempre con estas seis partes:
   1. Contexto: récords, sede, situación (playoff, home opener, revancha), lesiones, abridores o porteros (con fuente).
   2. Modelo: probabilidades, marcador o total esperado, spread / run line / puck line, confianza, estado de validación
      del mercado (skill, z, publicable o sin_validar) y sesgos conocidos.
   3.
