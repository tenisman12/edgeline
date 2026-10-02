---
description: Minería de datos con disciplina - probar una señal o feature nueva sin tocar los modelos congelados
argument-hint: "<hipótesis, p.ej. 'en NHL el equipo con 2 días de descanso contra back-to-back gana más de lo que dice el modelo'>"
---

Hipótesis: $ARGUMENTS

Sigue `CLAUDE.md`. Objetivo: saber si una señal agrega información medible, con el mismo rigor que
`utilidades/validar_mercados.py`. El riesgo principal de minar datos es encontrar patrones por azar; este protocolo existe para eso.

## Protocolo (no saltar pasos)
1. **Escribir la hipótesis antes de ver resultados**: deporte/liga, mercado, señal exacta, dirección esperada y
   métrica (Brier, log-loss, MAE). Guardarla en `trabajo/minar/<fecha>_<tema>.md`. Una hipótesis por corrida.
2. **Datos**: `datos/<deporte>.csv` (si no está, traer la rama datos:
   `git fetch origin datos && git worktree add trabajo/datos origin/datos` o pedirle a Alejandro que corra en su PC).
   Para señales de predicciones ya hechas: `salida/historial_predicciones_calificado.csv`.
3. **As-of estricto**: la señal de cada partido se calcula solo con información anterior a ese partido.
   Prohibido usar estadísticas de temporada completa, cierres de línea o resultados del mismo día.
4. **Contra qué se mide**: residuo del modelo actual (resultado − probabilidad del modelo). La pregunta es
   "¿la señal explica lo que el modelo falla?", no "¿la señal predice el resultado?".
5. **Partición temporal**: 70% más antiguo para explorar, 30% más reciente intacto. Todo ajuste se decide en el 70%.
   El 30% se mira UNA vez al final.
6. **Criterio** (el de la casa): n>=300 en el tramo de prueba, mejora a la base, z>=2.0 por error pareado,
   mejora en las dos mitades, calibración |p media − tasa real|<=0.04. Si se probaron k variantes, reportar k
   y exigir z>=2.0 en la variante elegida igual.
7. **Contra el mercado** cuando haya cuotas (`datos/mercado/`, `salida/cuotas_sharp_2026.csv`): ¿la señal mejora
   también contra la probabilidad sin vig del cierre? Si solo mejora a la tasa base, decirlo.

## Entregable
- Script en `utilidades/minar_<tema>.py` (lee `EDGELINE_BASE`, sin llaves, salida en pantalla y en
  `trabajo/minar/`), con su comando listo para PowerShell.
- Resumen: n, métrica base vs con señal, z, mitades, calibración, k variantes, veredicto
  (`pasa` | `no pasa` | `muestra insuficiente`).
- Si pasa: proponer cómo entraría (indicador de contexto o feature del modelo) y esperar la aprobación de Alejandro.
  No modificar `modelos/` ni `nucleo/` en esta corrida.

Ideas ya registradas para minar (pedir confirmación antes): influencia de abridor/portero/QB, descanso y viajes,
movimiento de línea como señal, osciladores contra residuo, CLV de los picks, estadísticas ricas de `datos/equipos/`.
