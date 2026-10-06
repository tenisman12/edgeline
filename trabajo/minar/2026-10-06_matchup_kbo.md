# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Liga: KBO. Mercado: total de carreras (y over/under en la línea ~promedio).
Problema: el modelo suma ataque del equipo y calidad del abridor por separado (efecto aditivo).
Señal: interacción log5 entre el abridor y el lineup rival, as-of:
  HR: tasa esperada = hr_abridor × hr_lineup / hr_liga; señal = esa tasa − (hr_abridor + hr_lineup − hr_liga).
  K:  igual con ponches por bateador enfrentado (contacto contra poncheador).
  Se suma para los dos abridores y se multiplica por los bateadores que enfrenta cada abridor (≈ IP esperadas × 4.3).
  Abridor: sus aperturas de la temporada actual y la anterior, encogidas a la liga (150 bateadores).
  Lineup: lo que bateó el equipo contra todos los lanzadores en la temporada, encogido (400 bateadores).
Dirección esperada: más HR esperados por interacción → más carreras; más K → menos carreras.
Contra qué: residuo del total del modelo actual con la capa de abridores (walk-forward, bloques de 30 días).
Variantes (k = 3): HR, K, HR+K. 70 % antiguo para ajustar, 30 % reciente una vez.
Métrica: MAE y MSE del total; log-loss del O/U en la línea ~promedio. Criterio de la casa.

## Resultado (30 % final, 1,081 juegos desde 2025-06-08; mirado una vez; k = 3)
- HR: MAE −0.002 (z −0.83), O/U −0.27 milésimas. K: MAE −0.004, O/U −0.75. HR+K: MAE −0.006, O/U −1.11.
Veredicto: NO PASA. La dirección de los coeficientes es la esperada (HR +, K −), pero el efecto de interacción
no agrega nada sobre el modelo aditivo con abridores: empeora un poco fuera de muestra.
