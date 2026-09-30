# Edgeline

Plataforma de predicción deportiva multi-deporte y multi-mercado.

```
colectores/   bajan datos (uno por fuente). Escriben en data_maestra/
nucleo/       io, features, evaluar, calibrar, mercado, indicadores, equipos, estado (compartido)
modelos/      un modelo por deporte (beisbol, hockey, americano, nba, futbol, tenis)
express/      predicción de hoy autónoma por deporte
utilidades/   diagnósticos y evaluación (evaluar_senales, explorar_espn, panel_jugador...)
datos/        <deporte>.csv, lo llena actualizar_todo.py
contexto/     proximos_espn.json (partidos por jugar + líneas + lesiones)
salida/       proximos.json, historial_picks.csv, plataforma_draft.html
```

Flujo:
1. `python actualizar_todo.py` baja y deja `datos/` al día (`--completo` la primera vez).
2. `python plataforma.py --dias 3` predice los partidos de los próximos días.

Variable de entorno `EDGELINE_BASE` = carpeta del repo. La llave de The Odds API va en
`EDGELINE_ODDS_KEY` (nunca en el código).

Los modelos están congelados. ESPN (lesiones, líneas, H2H, ATS, últimos 5) es solo contexto.
