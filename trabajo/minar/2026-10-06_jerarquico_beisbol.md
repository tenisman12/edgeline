# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Ligas: las siete de béisbol (MLB, NPB, KBO, LMP, LVBP, LIDOM, ABL). Mercado: ganador.

Problema. El ganador de béisbol se predice con una logística de 13 features de diferencia entrenada POR LIGA
(`modelos/beisbol.entrenar_logistica`, L2=1.0). Las ligas con menos juegos son donde el modelo apenas pasa
validación y donde cada capa nueva falla por muestra.

Señal. Los coeficientes de esas 13 features no tienen por qué ser distintos entre ligas: el béisbol es el mismo
juego. Un modelo multinivel que comparta los coeficientes entre las siete ligas, con intercepto propio por liga
(ventaja local distinta) y encogiendo las desviaciones de cada liga hacia el coeficiente común, debería estimar
mejor en las ligas chicas sin perder en la grande. Además, la fuerza de cada equipo como efecto aleatorio
(ridge sobre dummies de equipo) encoge a los equipos con pocos juegos hacia la media de su liga.

Variantes (k = 3):
- B: coeficientes comunes a todas las ligas + intercepto por liga.
- C: B + desviación por liga encogida (L2 fuerte sobre la desviación).
- D: C + efectos aleatorios de equipo.

Dirección esperada. Mejora en las ligas chicas; en MLB, empate o mejora chica.

Contra qué. Walk-forward por bloques de 60 días, 30 meses, 15 bloques. Rival: la logística actual por liga
reentrenada en cada bloque. Base: frecuencia histórica de victoria local. Métrica: log-loss pareado.
Criterio de la casa: n ≥ 300, z ≥ 2.0, mejora en las dos mitades, |p media − tasa| ≤ 0.04.

Ajuste: logística penalizada por IRLS (Newton con ridge por bloque de parámetros), 8 iteraciones. La
penalización distinta por bloque es el encogimiento parcial.

## AVISO: la primera corrida fue inválida
La primera medición corrió con una copia local de `datos/` incompleta: KBO tenía 689 juegos de los 4,377 reales
(84 % faltante), hockey la mitad, americano el 60 % y NBA un tercio. Con esa copia, KBO salía con n=238 y
"no evaluable", lo que hacía ver la hipótesis como plausible. Todo lo de abajo es de la corrida con datos
completos más `python utilidades\semillas.py mezclar`, que es lo que hace `actualizar_todo.py` en el workflow.

## Resultado (15 bloques, datos completos, mirado una vez; k = 3)
Mejora en milésimas de log-loss; positivo = la variante le gana al modelo actual.

- **B KBO** n=2,066: +0.45 (z 0.34), mitades +0.51/+0.39. **No pasa.**
- **B MLB** n=7,108: +2.32 (z 3.38), mitades +3.70/+0.95, p 0.532 vs 0.531. Pasa.
- **B NPB** n=2,508: +3.05 (z 2.73), mitades +5.37/+0.73, p 0.524 vs 0.529. Pasa.
- C KBO: +0.18 (z 1.33). C MLB: +0.24 (z 3.51). C NPB: +0.63 (z 3.34). Magnitudes despreciables.
- D KBO: −2.03. D MLB: **−3.32 (z −2.61)**. D NPB: −2.06. No pasa en ninguna.

Impacto en la probabilidad (variante B): MLB promedio 1.83 pp, NPB 2.09 pp, KBO 2.16 pp. A cuota 2.00 los dos
modelos caen a lados opuestos del umbral de decisión en el 7.8 % de los lados en MLB, 12.8 % en NPB, 13.0 % en KBO.

## Validación oficial, TODAS las ligas (`validar_mercados.py --deporte beisbol`, datos completos + semillas)
Columna 1 = liga sola (producción actual). Columna 2 = multinivel. Solo el ganador, que es lo que se apuesta.

- MLB n=4,797: z **+2.81 → +3.05**. Publicable en los dos. Mejora.
- NPB n=1,697: z **+2.61 → +2.66**. Publicable en los dos. Mejora marginal.
- KBO n=1,402: z **+3.68 → +3.46**. Publicable en los dos. Empeora.
- LMP n=350: z **+1.97 → +1.73**. Sin validar en los dos. Empeora.
- LVBP, LIDOM, ABL: muestra insuficiente en la ventana de 24 meses, no se miden.
- Efecto colateral: la run line del favorito en KBO pasa de publicable (z 2.25) a sin validar (z 1.91). No se
  apuesta run line, así que es un costo sin consecuencia práctica.
- Totales y over/under: idénticos en las dos configuraciones. El encogimiento no los toca porque salen de
  `carreras_esperadas`, no de la logística.

## Veredicto: NO SE APLICA
La variante B pasa el criterio en MLB y NPB en la prueba pareada, y en la validación oficial sobre las cuatro
ligas medibles **dos mejoran y dos empeoran**: +0.24 de z en MLB, +0.05 en NPB, −0.22 en KBO, −0.24 en LMP.
Es un empate, y de propina cuesta la validación de una run line. Ante un empate, se queda lo que ya está
validado y es más simple de auditar. El código de producción quedó sin cambios.

Lecturas que sí sirven:
1. **La hipótesis queda falsificada en su punto central.** Se escribió que las ligas chicas ganarían más. KBO,
   que con la copia incompleta parecía chica, tiene 4,221 juegos y no gana nada (+0.45, z 0.34). La ganancia
   aparece en MLB y NPB, las dos con más datos. Lo contrario de lo predicho.
2. **B le gana a C.** Permitir que cada liga se desvíe del coeficiente común baja la mejora de +2.32 a +0.24 en
   MLB. Los coeficientes de verdad son casi los mismos entre ligas; dejar desviaciones solo mete ruido.
3. **Los efectos aleatorios de equipo estorban.** D empeora MLB con z −2.61. El ELO ya lleva la fuerza del
   equipo; un parámetro por equipo la cuenta dos veces. Es el séptimo intento de agregar estructura al modelo
   de béisbol que falla.
4. **La ventaja de local por liga, que salió del ajuste, sí es un dato útil**: intercepto 0.022 en KBO (50.6 %
   con features neutras), 0.043 ABL, 0.108 NPB, 0.132 MLB (53.3 %), 0.144 LMP, 0.17 LIDOM, 0.189 LVBP. La
   ventaja de local en KBO es casi inexistente y en las invernales del Caribe es el doble que en MLB.
5. **El IRLS es 10 veces más rápido** que el descenso de gradiente de 400 iteraciones (0.6 s contra 6.0 s para
   9,500 juegos). Si algún día se toca `entrenar_logistica`, ese cambio sí vale por sí solo.

## Para repetirlo
`python utilidades\minar_jerarquico_beisbol.py --bloque 60 --meses 30`. Requiere numpy (es el único archivo
del repo que lo usa; nada del pipeline lo importa) y que `datos/` esté completo con las semillas mezcladas.
