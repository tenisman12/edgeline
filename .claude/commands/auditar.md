---
description: Auditoría del track record - modelo, picks de VALOR y Picks IA, calibración y mercados que se caen
argument-hint: "[liga opcional]"
---

Liga: $ARGUMENTS (vacío = todas). Sigue `CLAUDE.md`. Solo cifras de los archivos.

```bash
git pull -q 2>/dev/null
python utilidades/calificar_picks.py
```

Reporta, por liga y total:
1. **Predicciones del modelo** (`salida/historial_predicciones_calificado.csv`): n calificados por mercado, acierto,
   Brier contra la probabilidad del mercado (`p_mercado`) cuando exista, MAE en conteos (breaks, games, totales).
2. **Calibración** por rangos de probabilidad (50-55, 55-60, ... ): p media contra tasa real y n de cada rango.
3. **Picks de VALOR** (`salida/track_record.json`): apuestas, unidades, ROI.
4. **Picks IA** (`salida/historial_ia.csv` contra resultados): por nivel PREMIUM/PICK/LEAN, unidades a stake plano 1 u.
   Comparar con lo que habría dado seguir solo al modelo en los mismos partidos.
5. **CLV**: si hay cuota de cierre en `salida/cuotas_sharp_2026.csv`, comparar la cuota tomada contra el cierre.
6. **Alertas**: mercados `publicable` cuyo desempeño real esté fuera de lo esperado; ligas sin calificar; picks pendientes viejos.

Con menos de 100 calificados en una liga, escribir "muestra chica" junto a la cifra y no sacar conclusiones.
Termina con una tabla resumen y como máximo tres acciones concretas, cada una con su comando.
