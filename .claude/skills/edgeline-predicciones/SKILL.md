Edgeline: predicciones desde el repo
Regla central: ningún número se inventa. Cada cifra que aparezca en la respuesta sale de un archivo del repo o de una fuente de internet citada. Si un dato no está en ninguno de los dos lugares, se escribe "sin dato" y se dice qué falta.

Paso 1. Traer el repo (siempre primero)
```bash

cd ~ && (test -d edgeline && cd edgeline && git pull -q || git clone --depth 1 https://github.com/tenisman12/edgeline.git)
cd ~/edgeline && git log -1 --format='%ci %s'
python3 -c "import json;d=json.load(open('salida/proximos.json'));print('generado',d['generado'],'| partidos',len(d['partidos']))"
Reportar en una línea la hora de la última corrida de predicciones y la del último snapshot de cuotas. Si proximos.json tiene más de 12 horas, decirlo.

Archivos que se usan:

salida/proximos.json: predicciones y ficha completa por partido.
salida/odds_snapshots_2026.csv: cuotas más recientes. Tomar el último ts_utc de cada game_id; si es más nuevo que proximos.json, usar esas cuotas.
salida/validacion_mercados.json y salida/validacion_futbol.json: estado y métricas de cada mercado (n, skill, z, p_media contra tasa_real, sesgo).
salida/track_record.json e historial_calificado.csv: resultados de picks anteriores.
Paso 2. Leer TODOS los bloques de cada partido
Nunca resumir solo con modelo y mercados. Por partido se leen:

modelo (y derivados en fútbol)
mercados, valor, cuotas, movimiento (incluida la serie)
validacion y alerta
consenso
forma: récord, racha, últimos 10, ventanas temp/local/visita/L10/L5, ELO, power, status, osciladores, ou4
h2h_datos
estadisticas_equipo
jugadores_clave
contexto: lesiones, últimos 5 de ESPN, predictor de ESPN, H2H de ESPN
bloques: qué falta y por qué
Para volcarlo, escribir un script en el scratchpad que imprima cada bloque por partido, filtrando por fecha y liga, y leer la salida completa. En NFL y MLB las estadísticas traen más de 100 campos: imprimir los relevantes (EPA, yardas, capturas, pérdidas, castigos; carreras, OPS, ERA, WHIP), pero leer el bloque entero.

Notas de lectura:

Los ultimos5 de ESPN vienen del más viejo al más nuevo y pueden incluir la temporada anterior.
porteros_usados en NHL siempre vale 2.0 y no aporta.
Con menos de 5 juegos en la temporada, los osciladores salen en 0: reportarlos como "sin señal".
Al inicio de temporada, la forma de los equipos que no han jugado es de la temporada anterior: decirlo.
Paso 3. Completar con internet solo lo que falte
Buscar únicamente lo que el repo no trae y que cambia la lectura:

porteros titulares (NHL)
abridores confirmados (MLB, si probable está vacío)
QB titular y reporte final de lesiones (NFL/NCAA)
cuotas de tenis o de partidos sin cuotas
clima en NFL al aire libre
fecha de inicio de temporada si hay duda de pretemporada
Usar WebSearch y WebFetch con fuentes primarias o especializadas (sitio oficial de la liga, ESPN, Daily Faceoff, Rotowire, casas de apuestas). Citar cada dato traído así. Si la búsqueda no lo encuentra o la página pide permiso, decir "sin dato" y seguir. Nunca estimar el dato faltante.

Paso 4. Análisis por partido (en este orden)
Contexto: récords, sede, lesiones, abridores o porteros, situación (playoff, home opener, revancha).
Modelo: probabilidades, marcador esperado, total, spread o puck line, confianza. Incluir la validación del mercado (skill, z, estado) y cualquier sesgo registrado.
Osciladores y forma: osciladores, L10/L5, splits local/visita, estadísticas de equipo, H2H, O/U recientes.
Mercado: probabilidad sin comisión, movimiento desde la apertura, predictor de ESPN.
Relación: dónde coinciden y dónde chocan las capas, con números.
Decisión y por qué.
Cuando el usuario pida "sin juicios de valor", escribir solo datos y reglas explícitas, sin adjetivos evaluativos.

Paso 5. Reglas de decisión
VALOR: mercado publicable + edge ≥ umbral_edge (0.03) + cuota ≥ 1.80 (−125). Un mercado sin_validar no genera pick de VALOR; si se da una lectura, marcarla como fuera del track record.
Sesgos: aplicar los sesgos de validación cuando existan (por ejemplo, NFL O/U: p_media 0.519 contra tasa real 0.485).
Desempate entre mercados que cumplen: contar indicadores independientes a favor y en contra (modelo, ESPN, movimiento, forma o diferencial, H2H, O/U recientes, lesiones), todos con el mismo peso, y reportar el conteo.
Alertas: un edge mayor a 15% casi siempre señala información que el modelo no tiene. Mencionarlo.
NHL: el ganador está sin_validar y los totales del modelo salen peor que la base. No usar el total del modelo como argumento.
Tenis: sin cuota no hay pick, solo predicción.
Parlays: recomendar apuestas sencillas; un parlay solo si se pide, chico y con piernas independientes.
Paso 6. Formato de salida
En español y con horas de CDMX.
Empezar por los picks y después el análisis.
Sin stakes ni pesos, salvo que el usuario los pida.
Cerrar con "Fuentes:" cuando se haya usado internet.
Evitar la construcción "no es X, sino Y".
Si se pide infografía: usar el tipo de artifact Design, una tarjeta por partido, sin stakes.
