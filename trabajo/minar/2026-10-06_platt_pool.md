# Hipótesis (escrita antes de ver resultados) — 2026-10-06

Deportes con dos ligas: americano (NFL + NCAAF) y basket (NBA + NCAA). Mercado: ganador.

Problema. `modelos/americano.py` y `modelos/nba.py` convierten la probabilidad cruda del ensamble (vista ELO
más vista anotación) en la final con una Platt de dos parámetros ajustada **por liga**. NFL tiene 1,488
partidos y NCAAF 4,254; NBA 5,269 y NCAA basquet 18,835. En cada deporte una liga tiene bastante menos muestra
que la otra.

Señal. El juego es el mismo: la relación entre la probabilidad cruda y la real no tiene por qué diferir entre
NFL y NCAAF. Ajustar la Platt con los pares de las dos ligas debería estimar mejor (a, b) en la liga chica sin
perder en la grande. Es la idea del modelo jerárquico de béisbol aplicada donde **sí** hay asimetría de muestra
(en béisbol las siete ligas eran grandes y por eso no pasó).

Variante (k = 1): la Platt se ajusta con los pares de las dos ligas; todo lo demás (acumuladores de equipo,
media de liga, sesgos del margen y del total) se queda por liga.

Dirección esperada: mejora en la liga con menos muestra; empate en la grande.

**Previsión escrita antes de medir:** con 1,488 pares de NFL, dos parámetros ya quedan bien determinados, así
que lo más probable es que NO pase.

Contra qué. Walk-forward por bloques de 60 días, 24 meses, 13 bloques, con el mecanismo de la casa (se parcha
`io.cargar_juegos` con un corte de fecha, igual que `validar_mercados.validar_equipos`). Rival: la Platt de su
propia liga entrenada con lo mismo. Base: frecuencia histórica de victoria local.
Criterio de la casa: n ≥ 300, z ≥ 2.0, mejora en las dos mitades, |p media − tasa| ≤ 0.04.

## Resultado (mirado una vez)
Milésimas de log-loss contra su propia Platt; positivo = la compartida gana.

Americano, 13 bloques:
- **NFL** n=569: **−8.94** (z −1.68), contra la base +37.95, mitades +10.17/−27.99, p media 0.571 vs tasa 0.545.
  No pasa, y empeora.
- **NCAAF** n=1,876: **−1.91** (z −1.61), contra la base +91.71, mitades −0.74/−3.08, p 0.598 vs 0.643.
  No pasa, y empeora.

Basket, 13 bloques:
- **NBA** n=2,633: **−17.40** (z −5.63), contra la base +37.03, mitades −17.70/−17.10, p 0.594 vs 0.551.
  No pasa, y empeora mucho.
- **NCAA basquet** n=12,317: **+1.34** (z +2.50), contra la base +69.36, mitades +1.26/+1.42, p 0.634 vs 0.663.
  Pasa el criterio.

## Veredicto: NO SE APLICA
Tres de los cuatro casos empeoran, y el único que pasa lo hace por el motivo equivocado.

1. **La hipótesis queda falsificada, y al revés de lo previsto.** Se escribió que ganaría la liga chica. En
   basket gana la **grande** (NCAA, 18,835 partidos, +1.34) y pierde la chica (NBA, 5,269, −17.40). La causa es
   mecánica: con 18,835 pares contra 5,269, la Platt compartida la domina NCAA. Así que NCAA recibe casi su
   propia calibración con un poco de ruido ajeno, y NBA recibe la de NCAA impuesta encima.
2. **El balance es claramente negativo.** Aplicarlo costaría 17.40 milésimas en NBA para ganar 1.34 en NCAA.
3. **La descalibración lo confirma.** La Platt compartida deja a NBA en 0.594 de probabilidad media contra
   0.551 de tasa real: 4.3 puntos porcentuales de sesgo, por encima del umbral de 0.04 de la casa. En NFL el
   sesgo pasa a 2.6 pp y las mitades se descuadran (+10.17 y luego −27.99), la firma de un ajuste chico siendo
   jalado por datos ajenos.
4. **NFL y NCAAF tienen calibraciones distintas de verdad.** Si fueran iguales, compartir no costaría nada.
   Que las dos empeoren significa que el sesgo favorito-longshot no es el mismo, y tiene sentido: en NCAAF hay
   favoritos de −2000 que en NFL no existen.

## Lo que cierra esto
Es la tercera vez que el encogimiento entre ligas falla, con tres diseños distintos:
- Béisbol, coeficientes de la logística compartidos entre siete ligas: empate (2 mejoran, 2 empeoran).
- Béisbol, efectos aleatorios de equipo: empeora (z −2.61 en MLB).
- Americano y basket, Platt compartida: empeora en 3 de 4.

El hallazgo general, que vale más que cualquiera de las tres pruebas: **las ligas ya tienen muestra suficiente
para estimar sus propios parámetros mejor que un estimador compartido.** La línea del encogimiento entre ligas
queda cerrada. Si alguna vez se agrega una liga realmente chica (menos de ~500 partidos), vale reabrirla solo
para esa liga.

## Lo siguiente, que esta prueba deja a la vista
NCAA basquet acaba de validar (ganador +14.8 % de skill con z 20.3, total +5.1 %, over/under +6.4 % con z 31.3
sobre 36,963 casos) y **no tiene ninguna capa medida**, al contrario de NHL, NFL, NBA y MLB. Con 18,835
partidos y un modelo que ya le gana a la base por 14.8 %, medir sus capas (descanso, back-to-back, net rating,
ritmo, viajes) con `utilidades/pesos_capas_v2.py` es el trabajo de modelado con mejor valor esperado disponible
hoy. La temporada arranca en noviembre.

## Para repetirlo
`python utilidades\minar_platt_pool.py --deporte americano --bloque 60 --meses 24` (y `--deporte basket`).
Solo stdlib.
