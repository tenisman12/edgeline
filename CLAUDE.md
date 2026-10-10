# Edgeline — instrucciones para Claude

Este archivo lo lee Claude Code al abrir el repo. Es la memoria del proyecto: arquitectura, reglas y comandos.
Dueño: Alejandro (tenisman12). Responder en español, horas de CDMX (UTC-6).

## Qué es
Plataforma de predicción deportiva multi-deporte y multi-mercado: béisbol (MLB, LMP, KBO, NPB, LVBP, LIDOM, ABL),
NFL y NCAAFB, NHL, SHL, Liiga, AHL y DEL, NBA y NCAAMB, fútbol (Premier, LaLiga, Serie A, Bundesliga, Ligue 1, Liga MX, MLS), tenis ATP/WTA.
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
   En los textos (lecturas, por_que_si/no, páginas) no se escribe "sin validar" ni "no validado" (9-oct-2026): se dice la
   consecuencia ("el modelo pesa la mitad", "p final = mercado") y la z. Los campos internos (`estado`, `veredicto`) no cambian;
   la confianza `no_validado` de decidir_v2 ahora se llama `solo_mercado`. Los ángulos dicen a quién favorecen y cuánto moverían
   (efecto de toda la muestra encogido, tanda 4; tope de 2 veces el x típico).
4. **Validación única y estricta** (walk-forward as-of contra línea base): n>=300, mejora a la base, z>=2.0
   (fútbol 1.64), mejora en ambas mitades, calibrado |p media - tasa real|<=0.04 (conteos: sesgo<=0.10 desv.).
   "Publicable" = supera la tasa histórica, NO a las casas. No hay edge demostrado contra el cierre (CLV pendiente).
5. **Pick/VALOR:** mercado `publicable` + edge >= `umbral_edge` + cuota >= 1.70 (-143), sin tope (acuerdo 6-oct). Stake plano 1 u.
   Todos los picks del modelo se guardan y se califican; el resultado se mide también por rango de cuota.
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
  p_final (Pinnacle 75% + modelo 25% en logit), pick de mayor EV (ML, cuota desde 1.70), confianza alta/media/baja/mínima (stake 3/2/1/0%)
  y conteo de señales de la lectura a favor / en contra. Coeficientes en `modelos/decidir_beisbol.json` (`utilidades/pesos_capas.py`).
- `salida/picks_del_dia.json` y `salida/historial_picks_dia.csv`: LA LISTA OFICIAL (`utilidades/picks_del_dia.py`): decisión de ganador y total
  para todos los partidos, y los mejores picks del día (beisbol: sistema estimado con confianza alta/media; demás deportes: Pick Premium
  premium/pick con EV ≥ 2%; cuota desde 1.70 sin tope; hasta un ganador y un total por partido; máximo 4 al día y 10% del bank). Solo ganador y totales. Cada pick lleva
  confianza, `por_que_si` y `por_que_no` (en picks_del_dia.json y en historial_picks_dia.csv).
  Se excluye (liga, mercado) cuando el historial en vivo promete ≥10 pp más de lo que acierta (n≥30, z≥2): `picks_del_dia.descalibrados()`.
  Al 6-oct-2026: totales de NCAAF (60% vs 39%, n 57) y games de WTA (58% vs 44%, n 57). Leans, mínima, revisar y lecturas
  sin precio se miden pero no son picks. Es lo único que se recomienda y lo que mide el track record público.
- Capa cualitativa (9-oct-2026, `nucleo/angulos.py`): cada partido de `picks_del_dia.json` trae `angulos` (situacionales activos con las
  mismas definiciones del minado: descanso, segunda noche, gira, rachas de 5, revancha, bajon, sandwich, primer juego en casa, fin de
  temporada, tras perder por mucho) con su efecto medido fuera de muestra (`modelos/angulos_medidos.json`, de trabajo/minar; se regenera con
  `python -m nucleo.angulos --catalogo`). Ninguno paso: no cambian p ni EV; se cuentan a favor / en contra del pick (|efecto| < 1 pp no
  cuenta) en por_que_si / por_que_no y en `historial_picks_dia.csv` (angulos, angulos_favor, angulos_contra). Todos los partidos se
  registran antes de empezar en `salida/historial_angulos.csv`; `utilidades/medir_angulos_vivo.py` los mide contra el resultado
  (`salida/angulos_vivo.json`, mismo protocolo). Uno que pase se le lleva a Alejandro; nada gana peso solo.
  Tanda 3 (9-oct, `utilidades/minar_angulos_tanda3.py`, `trabajo/minar/2026-10-09_tanda3.md`, k 35): pasan K14 ausencias NBA
  (z 3.97, +7.3 pp por 48 min de ausentes; en vivo sale del reporte de lesiones 'Out') y T1 minutos del partido anterior ATP
  (z 3.87, +3.4 pp por hora de mas del rival). APLICADAS con peso (aprobado 9-oct): plataforma.py suma beta*x al logit
  (NBA K14 beta 0.308 por 48 min, ATP T1 beta 0.164 por hora; `modelos/capas_ausencias_minutos.json`,
  `utilidades/pesos_ausencias_minutos.py`; K14 sigue pasando sobre la base de produccion, z 3.89). Se ven en
  modelo.capa_ausencias / modelo.capa_minutos y no se cuentan otra vez en la capa cualitativa. T3 carga de 14 dias en tenis mejora
  mucho pero al reves de lo registrado (el que trae mas partidos rinde mas): hipotesis nueva para medir en vivo.
  Tanda 4 (9-oct, `utilidades/minar_angulos_tanda4.py`, `trabajo/minar/2026-10-09_tanda4.md`, k 81): agrupados por liga,
  totales contra tasas de anotacion y contra el cierre (futbol O2.5, NFL), derbi y jugador local en tenis. Nada nuevo pasa
  (T2 tenis pasa sobre el modelo pero sobre la capa T1 da z 0.25). Coors +2.1 carreras (ya en la capa de parque).
  La parte A da el efecto de los 136 con IC y encogido (Bayes empirico): `2026-10-09_tanda4_resultados.json`.
  Tanda 5 (9-oct, `utilidades/minar_angulos_tanda5.py`, `trabajo/minar/2026-10-09_tanda5.md`, k 77; ideas de professormj):
  rachas cortadas, frio vs caliente, sequia, sorpresa, paliza, abridor vapuleado (LMP). Pasa S4 frio contra caliente en
  beisbol (z 2.02, +4.0 pp en toda la muestra; en los demas deportes va al reves). APLICADO con peso en beisbol (aprobado
  9-oct: "se aplica todo a beisbol"): plataforma.py suma beta 0.161 * x al logit (x +1 local frio contra visita caliente,
  `utilidades/pesos_frio_caliente.py`, clave beisbol_S4 en `modelos/capas_ausencias_minutos.json`); se ve en
  modelo.capa_frio_caliente y decidir.py lo suma a p_modelo.
- REGLA (9-oct-2026, Alejandro: "nunca lo olvides"): TODOS los angulos medidos se ponen donde apliquen, en cada partido y en
  cada analisis, con lo que moverian. Ganador: `nucleo/angulos.calcular` (tandas 1-5, derbi F18, abridor vapuleado S9 en LMP).
  Totales: `nucleo/angulos.calcular_totales` (TH/TK/TB/TF/TN de la tanda 4 y TS de la tanda 5: moveria +-x goles/carreras/
  puntos con su IC); `picks_del_dia.json` los trae en `angulos_total` y en por_que_si/no de los picks de total.
  Por equipo (tanda 6, `utilidades/minar_angulos_tanda6.py`, k 127): `nucleo/angulos.calcular_equipos` da el marcador con
  angulos (ataque propio y defensa del rival, encogido James-Stein) y el total como suma; en `picks_del_dia.json` ->
  `marcador_angulos`. Pasan NHL segunda noche ataque (-0.15 goles), NBA 3 en 4 defensa (+0.93 pts), NCAAMB gira defensa (+1.46).
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

- Capa de totales (9-oct-2026, Alejandro: "quiero los totales ya validados y listos"; `nucleo/capa_totales.py`, minado en
  `trabajo/minar/2026-10-09_capa_totales.md`, k 161): T* = a + b*T_modelo + c*media de liga con olvido + d*ritmo de los dos
  equipos + nivel reciente (ultimos 300 residuos); over/under con la distribucion de residuos del ultimo ano. La validacion
  oficial la ajusta bloque a bloque con 24 meses de precalentamiento y califica "Total esperado (capa)" y "Over/Under (capa)";
  al final escribe `modelos/capa_totales.json`. Over/Under (capa) publicable: NCAAMB z 34.6, NBA 9.7, NCAAFB 5.5, LMP 5.0,
  MLB 4.8, NPB 3.5, NFL 3.0. NHL y KBO no pasan (siguen con el total del modelo). plataforma.py usa la capa solo donde paso
  (modelo.capa_totales, total_modelo guarda el del modelo y los marcadores se escalan). NBA: la capa espera 15 juegos de
  temporada por equipo (en oct-nov subestima 6.4 puntos). decidir_v2 usa sus residuos tambien en lineas alternas.
- Picks de totales (9-oct-2026): la lista oficial admite hasta un ganador y un total por partido (tope 4 al dia); Picks IA
  puede guardar dos lecturas por partido (ganador y total). En beisbol el total pasa por decidir_v2 y el ganador sigue en
  decidir.py. "Publicable" = le gana a la tasa historica; contra la linea de la casa se mide en vivo.
- LMP (9-oct-2026): validacion oficial en `validacion_mercados.json` (beisbol_lmp: ganador z 2.6, run lines, Over/Under
  (capa) z 5.0). Cuotas: The Odds API no la cubre; `colectores/recolectar_cuotas_sgo.py` las baja de SportsGameOdds
  (secreto SGO_KEY, plan gratis 2,500 objetos al mes, foto cada 3 h en cuotas.yml) y las mezcla en cuotas_casas.json con
  sport baseball_lmp. "Tucson Baseball Team" (2025-26) = Mayos de Navojoa (`nucleo/io.EQUIPO_ALIAS`; el factor de parque
  sigue siendo el de la sede real). Capa de abridores: en LMP y NPB se aplica la parte del total (paso) y no la del ganador
  (`nucleo/abridores.aplica`). Action Network no cubre LMP: sin publico medido. Reglas nuevas 2026-27 (reloj de pitcheo,
  ABS, 3 bateadores por relevista): el nivel reciente de la capa se ajusta solo con los primeros juegos; se mide en vivo.

## Hockey: SHL, Liiga, AHL y DEL (10-oct-2026, Alejandro: "igualito al de NHL")
- Datos: `colectores/recolectar_hockey_ligas.py` (fuentes oficiales: stats.swehockey.se, liiga.fi/api/v2, HockeyTech de la
  AHL, penny-del.org). Mismas columnas que NHL en `datos/hockey.csv` (columna `league`: SHL, LIIGA, AHL, DEL) mas `goals_reg`
  (goles al minuto 60), `xg` (solo Liiga) y `pp_pct`. AHL con nombre completo (sus codigos chocan con NHL: CHI, SJ).
  Diario en `actualizar_todo.py` (paso hockey_ligas, `--solo-actual`); la historia 2024-25+ entra por `semillas/hockey_ligas.csv`
  (`python utilidades/semillas.py exportar hockey_ligas` en la PC). SHL 2024-25 falta (swehockey no muestra su id).
- Calendario: `colectores/proximos_hockey.py` (como proximos_beisbol). Cuotas: The Odds API `icehockey_sweden_hockey_league`,
  `icehockey_liiga`, `icehockey_ahl` (solo eu, h2h y totals: 2 creditos por foto). La DEL no esta en The Odds API.
- Modelo: `modelos/hockey.py` entrenado por liga (`entrenar("shl")`); sin liga = NHL (los llamados viejos no mezclan).
  Liiga mezcla su xG por partido igual que NHL con MoneyPuck. Nuevo en todas las ligas de hockey: 1X2 a 60 minutos (`p_60`,
  Poisson sin calibrar; "Empate a 60 min" en la validacion: subestima el empate, 16% vs 22%, sin validar).
- Validacion (`validar_mercados.py --deporte hockey` = NHL + las cuatro, claves hockey_shl...): al 10-oct, Ganador publicable en
  Liiga (Brier +5.0%), AHL (+2.1%) y DEL (+12.1%); SHL con 412 juegos no llega a los 500 del validador. Totales sin validar
  salvo el total esperado de Liiga. Publicable = le gana a la tasa historica, no a las casas.
- Angulos: los mismos de NHL medidos en cada liga por separado (`utilidades/minar_angulos_hockey_ligas.py` ->
  `trabajo/minar/2026-10-10_hockey_ligas_resultados.json`, k 154, ninguno pasa). `nucleo/angulos.py` los pone en cada
  partido (ganador H/Q/S, totales TH/TS, por equipo) con lo que moverian. Sin altitud (H24, TH5) ni porteros (H19, H20, TH7):
  estas fuentes no traen el titular. PESO_MODELO 0.5 como NHL en decidir_v2.
- Angulos juntos (10-oct, `utilidades/minar_angulos_bayes_hockey.py`, `trabajo/minar/2026-10-10_bayes_hockey.md`): logistica
  bayesiana jerarquica con los 29 angulos de ganador y efectos compartidos entre las 5 ligas, walk-forward mensual (9,024
  partidos): z -0.95, no pasa (DEL empeora, z -3.33). Boosting z -0.54; red neuronal z -9.13 (sobreajusta). El tau elegido es
  el minimo: los angulos no agregan nada al modelo de hockey. Siguen como contexto. Los Q de las ligas nuevas ahora se
  encogen (`nucleo/angulos.encoger_crudo`).

## Notas de lectura
- `ultimos5` de ESPN van del más viejo al más nuevo y pueden incluir la temporada anterior.
- `porteros_usados` en NHL siempre vale 2.0.
- Con menos de 5 juegos en la temporada los osciladores salen en 0: "sin señal".
- Osciladores: SIEMPRE se muestran en cada análisis y en por_que_si / por_que_no (`picks_del_dia.osciladores_txt`), sin peso en p.
  Minado 6-oct-2026: NBA z 3.2 sobre el modelo base, z 1.1 sobre las capas de producción (no pasa); NHL, MLB, KBO cero.
- Pick Premium con temporada recién iniciada (`plataforma.temporada_corta`: menos de 5 juegos en la temporada actual, NFL/NCAAFB menos de 3,
  o último juego hace más de 60 días): forma, osciladores y racha no puntúan, fuerza usa solo el ELO, nunca premium; la razón lo dice.
- NHL: ganador `publicable` desde oct-2026 (z 4.5, n 2,818) pero sin ventaja contra el cierre todavia (CLV z 0.2); no usar el total del modelo como argumento.
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
- Velocidad del torneo y saque por superficie en BREAKS de tenis (`nucleo/velocidad_tenis.py`, minado el 6-oct-2026,
  `trabajo/minar/2026-10-06_velocidad_tenis.md`): O/U de breaks ATP bo3 skill 11.2% -> 12.6% (z 17.3), ATP bo5 5.3% -> 8.1%
  (z 5.2), WTA bo3 4.1% -> 4.6% (z 8.4). Aplicado en plataforma y en la validacion. Torneo rapido -> menos breaks.
  El torneo de ESPN se casa con el de TML por el ultimo partido de los dos jugadores (o alias).
- Futbol forma rapida (9-oct-2026, aprobado por Alejandro): `modelos/futbol.py` ELO K 20 -> 40 y OLVIDO 0.98 en las tasas de goles
  (antes todo el historial pesaba igual). Fuera de muestra 1X2 z 1.82 (umbral 1.64), over 2.5 z 1.19; validacion oficial 80 -> 89
  publicables (MLS ganador/empate/totales, Premier y Serie A por 2 goles). La mejora viene de MLS, Liga MX y Premier; Serie A,
  Bundesliga y Ligue 1 bajan poco. Contra el cierre de Pinnacle sigue sin aportar. `trabajo/minar/2026-10-09_forma_rapida.md`.
- CLV (`utilidades/clv.py`, salida/clv.json): picks contra el cierre de Pinnacle y si el cierre se mueve hacia el modelo.
  NHL/MLB: las fotos h2h a 3 vias (casas europeas, tiempo regular) se pasan a 2 vias; desde el 6-oct el colector guarda
  2 vias fuera del futbol. El CLV solo se calcula cuando el partido ya empezo.

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
