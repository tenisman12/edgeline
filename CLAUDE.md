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
5. **Pick/VALOR:** mercado `publicable` + edge >= `umbral_edge` + cuota >= 1.70 (-143) y <= 3.00 (+200). Stake plano 1 u.
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
- `salida/decidir.json` y `salida/historial_decidir.csv`: sistema estimado de béisbol (`utilidades/decidir.py`): p_modelo (ELO + diferencial + abridor),
  p_final (Pinnacle 75% + modelo 25% en logit), pick de mayor EV (ML o run line, cuota 1.70–3.00), confianza alta/media/baja/mínima (stake 3/2/1/0%)
  y conteo de señales de la lectura a favor / en contra. Coeficientes en `modelos/decidir_beisbol.json` (`utilidades/pesos_capas.py`).
- `salida/picks_del_dia.json` y `salida/historial_picks_dia.csv`: LA LISTA OFICIAL (`utilidades/picks_del_dia.py`): decisión de ganador y total
  para todos los partidos, y los mejores picks del día (beisbol: sistema estimado con confianza alta/media; demás deportes: Pick Premium
  premium/pick con EV ≥ 2%; cuota 1.70–3.00; un pick por partido; máximo 4 al día y 10% del bank). Leans, mínima, revisar y lecturas
  sin precio se miden pero no son picks. Es lo único que se recomienda y lo que mide el track record público.
- `salida/publico.json` y `salida/publico_<año>.csv` (`colectores/recolectar_publico.py`): el público medido directo: % de boletos y % de dinero
  por lado (ML, spread, total) del tablero público de Action Network (NFL, NBA, MLB, NHL, NCAA) y número de notas de Google News por equipo
  en 48 h. Los porcentajes son la MEDIANA de las casas que reportan (0 y 100 = sin dato). Cada pick oficial guarda `publico_boletos`,
  `publico_dinero` y las notas; `calificar_picks.py --ver` los agrupa en "público con el pick / contra el pick / contra pero el dinero con
  el pick / repartido", que es la prueba de si ir contra el público paga.
- `salida/historial_picks_dia.csv` guarda, por pick, `mov_linea` (movimiento de la línea sharp EN EL LADO DEL PICK desde la apertura,
  en puntos porcentuales; de `mercado_publico.json`) y `senales_mercado`. Es contexto que se mide: no cambia `p` ni el EV.
  `utilidades/validar_movimiento.py` mide si ir con el movimiento paga (apertura vs cierre de `cuotas_sharp_<año>.csv` contra el
  resultado real): n, esperado vs real, z, unidades, por liga y por mitades, con el veredicto del protocolo (n≥300, z≥2.0, las dos
  mitades). Corre en cada actualización. Mientras diga `SIN VALIDAR` no decide nada.
  `utilidades/validar_contrapublico.py` mide las reglas clasicas de ir contra el publico como apuestas sombra de 1 u:
  R1 under cuando el over trae ≥80% de los boletos, R2 dog cuando el favorito trae ≥70%. Usa el precio sin vig como
  esperado (del over/under cuando el colector lo guarda, −110 si no) y da n, z, unidades, por liga y por mitades.
  Corre en cada actualización. R3 (el favorito no cubre) falta: el CSV no guarda precio de spread ni marcador por equipo.
  `utilidades/validar_publico.py` dice si ese dato sirve: cobertura, % de extremos, correlación entre boletos y probabilidad implícita
  (el público apuesta favoritos: r 0.6–0.9 = creíble) y la brecha dinero−boletos por partido.

## Notas de lectura
- `ultimos5` de ESPN van del más viejo al más nuevo y pueden incluir la temporada anterior.
- `porteros_usados` en NHL siempre vale 2.0.
- Con menos de 5 juegos en la temporada los osciladores salen en 0: "sin señal".
- Pick Premium con temporada recién iniciada (`plataforma.temporada_corta`: menos de 5 juegos en la temporada actual, NFL/NCAAFB menos de 3,
  o último juego hace más de 60 días): forma, osciladores y racha no puntúan, fuerza usa solo el ELO, nunca premium; la razón lo dice.
- NHL: ganador `sin_validar`; no usar el total del modelo como argumento.
- El público de NHL carga el over en toda la liga (mediana 92% de boletos). No es error de lectura: la línea de totales
  se movió 5.5 → 6.0 en cinco partidos, o sea hacia el over. El dato se usa y se mide; `TOTAL_PUBLICO_VETADO` quedó vacío.
- Tenis: TML fecha con el inicio del torneo; la llave no lleva fecha.

## Capas medidas el 5-oct-2026 (manual: Actions -> "medir capas"; los .json quedan en modelos/)
- Porteros NHL (GSAx as-of, `utilidades/medir_porteros_nhl.py`): total esperado mejora z 3.0 en las dos mitades; ganador y
  O/U sin cambio. Aplicado en `modelos/hockey.py` (GSAX_BETA 0.25, K 40, ultimas 40 aperturas). El ajuste viejo por save%
  de ventana queda solo como dato. O/U de NHL sigue sin validar (p media 0.431 vs real 0.415: el modelo carga el over).
- Viajes NHL/NBA (km y husos, `utilidades/medir_viajes.py`): sin efecto medible. Contexto.
- Clima MLB (`utilidades/medir_clima_mlb.py`, MLB Stats API trae viento relativo al campo): MSE z 3.5, MAE z 0.9.
  +0.035 carreras por grado F, +0.033 por mph hacia afuera. Se muestra "Total con clima" junto al total del modelo.
- Umpire MLB: sin efecto (z negativo). Arbitros NHL (4,231 partidos): goles totales sin efecto (MSE z -2.5); minutos de
  castigo si (MAE z 13.7), sin uso en mercados de goles. Clima NFL (1,163 partidos): MAE z 2.3 pero falla una mitad: contexto
  (viento -0.50 puntos por mph arriba de 10).
- Abridores KBO (`nucleo/abridores.py`, box oficial 2021-2026, `utilidades/medir_abridores_kbo.py`): ganador pasa de z 1.67
  (sin_validar) a z 3.42 (publicable, Brier +3.1%). K 0.45 por carrera salvada; total esperado -0.25 x valor del abridor
  rival (MAE z 5.4); O/U sin mejora. Aplicado en plataforma (KBO) y en la validacion.
- CLV (`utilidades/clv.py`, salida/clv.json): picks contra el cierre de Pinnacle y si el cierre se mueve hacia el modelo.

## Completar datos (utilidades/completar_datos.py)
Corre al final de `actualizar_todo.py` (cada hora en Actions). Llena las celdas vacias de `datos/<deporte>.csv` con
`datos/equipos/` y nunca pisa un dato existente: NHL (tiros, hits, bloqueos, PP, portero abridor), NFL/NCAAF (yardas, downs,
perdidas, castigos, EPA en NFL, posesion), NCAAMB (box completo), NBA (play-in y playoffs desde ESPN, columna `tipo`),
futbol (tiros/corners/tarjetas de Liga MX y MLS; posesion, pases y demas en las 7 ligas desde ago-2023), beisbol NPB/KBO
(espejo bateo = pitcheo del rival, comprobado 100 % en MLB; tasas acumuladas como MLB). Escribe `salida/cobertura_datos.json`
(por archivo, liga y columna: % con dato y fechas). Relleno historico por ESPN: workflow manual `rellenar.yml`.

## Datos históricos (rama "datos")
Al inicio de cada sesión, antes de analizar, traer la rama de datos:
git fetch origin datos:refs/remotes/origin/datos && git worktree add trabajo/datos origin/datos
Quedan en trabajo/datos/datos/ y se pueden leer libremente para cualquier análisis.
