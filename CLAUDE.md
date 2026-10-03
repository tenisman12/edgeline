# Edgeline — instrucciones para Claude

Este archivo lo lee Claude Code al abrir el repo. Es la memoria del proyecto: arquitectura, reglas y comandos.
Dueño: Alejandro (tenisman12). Responder en español, horas de CDMX (UTC-6).

## Qué es
Plataforma de predicción deportiva multi-deporte y multi-mercado: béisbol (MLB, LMP, KBO, NPB, LVBP, LIDOM, ABL),
NFL y NCAAFB, NHL, NBA y NCAAMB, fútbol (Premier, LaLiga, Serie A, Bundesliga, Ligue 1, Liga MX, MLS), tenis ATP/WTA.
Los picks se venden en su página The Bet Model (TBM). Este repo es público.

```
colectores/   bajan datos a data_maestra/
nucleo/       io, features, evaluar, calibrar, mercado, indicadores, equipos, estado, forma, linea, jugadores
modelos/      beisbol, hockey, americano, nba, futbol, futbol_mercados, tenis
utilidades/   validar_mercados, validar_futbol_mercados, calificar_picks, ver_predicciones, picks_ia,
              volcar_partidos, guardar_lecturas, ...
ia/           instrucciones_picks.md (criterio de Picks IA, compartido por la API y por las sesiones)
salida/       proximos.json, historial_*.csv, track_record.json, validacion_*.json, picks_ia.json
datos/        <deporte>.csv (rama "datos" en GitHub; no está en main)
```
Flujo: `actualizar_todo.py` (datos) -> `plataforma.py --dias 7` (predice) -> `calificar_picks.py` (track record).
GitHub Actions: `actualizar.yml` 05:37, 13:37 y 19:37 UTC (jugadores, validacion, Picks IA); `cuotas.yml` cada hora (resultados, cuotas si la foto tiene 3 h o mas, picks y calificacion). GitHub puede retrasar corridas horas: no depender de la hora exacta.

## Reglas que no se rompen
1. **Ningún número se inventa.** Toda cifra sale de un archivo del repo o de una fuente de internet citada.
   Si falta, se escribe "sin dato" y se dice qué falta.
2. **Modelos congelados.** ESPN, jugadores, lesiones y cuotas son contexto; no cambian probabilidades del modelo.
   Cualquier cambio a un modelo pasa primero por la validación (regla 4) y lo aprueba Alejandro.
3. **Nunca esconder datos.** Todos los partidos, todos los mercados, mismos bloques en todos los deportes.
   Un mercado que no pasa la validación se muestra como `sin_validar`, no se borra.
4. **Validación única y estricta** (walk-forward as-of contra línea base): n>=300, mejora a la base, z>=2.0
   (fútbol 1.64), mejora en ambas mitades, calibrado |p media - tasa real|<=0.04 (conteos: sesgo<=0.10 desv.).
   "Publicable" = supera la tasa histórica, NO a las casas. No hay edge demostrado contra el cierre (CLV pendiente).
5. **Pick/VALOR:** mercado `publicable` + edge >= `umbral_edge` + cuota >= 1.80 (-125) y <= 3.00. Stake plano 1 u.
   Sin cuota no hay pick. Criterio completo en `ia/instrucciones_picks.md`.
6. **Pretemporada y juegos "If Necessary"** fuera de VALOR y track record.
7. **Llaves** solo en variables de entorno / secretos (`EDGELINE_ODDS_KEY`, `ANTHROPIC_API_KEY`). Nunca en código ni chat.
8. **Licencias:** TML (CC BY-NC-SA), ESPN y MLB Stats API no permiten uso comercial claro. No subir datos crudos.
9. Estilo: directo, sin la construcción "no es X, sino Y". Sin adjetivos cuando Alejandro pida "sin juicios".

## Cómo trabajar con Alejandro
- Usa Windows + PowerShell en `C:\Edgeline_repo`. Toda instrucción va con comandos listos para copiar y pegar:
  `cd C:\Edgeline_repo` y `$env:EDGELINE_BASE = "C:\Edgeline_repo"` al inicio.
- Para editar Python a mano: primero `notepad C:\Edgeline_repo\ruta\archivo.py`, luego el código, luego el comando para correrlo.
- Trabajo por bloques cerrados: un cambio, una verificación suya. No adelantarse al siguiente paso.
- Orden vigente: 3) Actions con ESPN, 4) Picks IA y track record, 5) la página al final.

## Comandos del proyecto (escribe /nombre)
- `/hoy [fecha] [ligas]` — lectura completa de los partidos y decisión por partido (Picks IA en sesión).
- `/minar <hipótesis>` — probar una señal o feature nueva con el protocolo de validación, sin tocar los modelos.
- `/auditar` — estado del track record, calibración, Picks IA contra el modelo, mercados que se caen.

## Archivos clave al leer predicciones
- `salida/proximos.json`: ficha completa por partido (`ficha: 2`). Volcar con `python utilidades/volcar_partidos.py`.
- `salida/odds_snapshots_2026.csv` y `salida/cuotas_sharp_2026.csv`: cuotas más recientes por `game_id`.
- `salida/mercado_publico.json`: lectura sharp vs público por partido (Pinnacle/bolsas contra DraftKings/FanDuel/BetMGM...): movimiento de cada grupo desde la apertura, brecha y señales (SHARP, SOLO PUBLICO, PUBLICO cargado, SHARP CONTRA PUBLICO, LINEA). Se refresca en cada foto de The Odds API (`utilidades/mercado_libros.py --ver`). No son splits reales de boletos/dinero.
- `salida/validacion_mercados.json`, `salida/validacion_futbol.json`: estado y métricas de cada mercado.
- `salida/track_record.json`, `salida/historial_calificado.csv`, `salida/historial_predicciones_calificado.csv`.

## Notas de lectura
- `ultimos5` de ESPN van del más viejo al más nuevo y pueden incluir la temporada anterior.
- `porteros_usados` en NHL siempre vale 2.0.
- Con menos de 5 juegos en la temporada los osciladores salen en 0: "sin señal".
- NHL: ganador `sin_validar`; no usar el total del modelo como argumento.
- Tenis: TML fecha con el inicio del torneo; la llave no lleva fecha.
