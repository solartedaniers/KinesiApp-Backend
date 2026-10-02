# REPORT — Spike de MediaPipe Pose (Fase 0.5)

> **Corrida principal: videos propios, 2026-10-01 (noche).** Reemplaza las conclusiones de la
> corrida con grabaciones de pantalla (Anexo A) y de la sintética (Anexo B). Spike desechable: no
> toca `app/` ni implementa nada del dominio de IA.

## 0. Verificación previa de los videos (antes de cualquier análisis)

| Condición | ¿Se cumple? | Detalle |
|---|---|---|
| **Grabados directamente con el celular, no captura de pantalla** | **Sí** | Habitación real, sin interfaz superpuesta, sin moiré ni doble exposición. Pero los 4 archivos están **reprocesados a 474×850 y a ~16,6 fps**, muy por debajo de los 30 fps de una cámara de celular (probablemente pasaron por una app de mensajería), y tienen **mucho desenfoque por movimiento**. |
| **Una sola persona en cuadro** | **Sí, con un riesgo** | Una sola persona real, pero **detrás hay un espejo que la refleja** en casi todos los frames: hay una segunda figura humana en la imagen (ver §3 sobre si el rastreo la confunde). |
| **Cuerpo completo** | **Parcial** | Sentadillas: completo. Saltos: en el punto más alto **se cortan la cabeza y los brazos**, y en `salto_mal_echo` **los pies salen del cuadro por abajo** al final y quedan al borde en algunos aterrizajes. Caderas, rodillas y tobillos están en cuadro casi siempre. |
| (Extra) Vista y cámara | **Oblicua (~3⁄4), en mano** | Ni lateral ni frontal. La cámara se mueve un poco entre frames. |

Conclusión de la verificación: **se cumplen lo suficiente para analizar** (no son grabaciones de
pantalla y hay una sola persona real), pero con limitaciones que afectan la precisión absoluta:
16,6 fps, vista oblicua, pies al borde del cuadro y el espejo. Se analiza igual y cada limitación
se marca donde pesa.

Hojas de contacto (10 frames por video): `output/contact2/<video>.jpg`.

## 1. Veredicto

**Esta vez sí hay evidencia clara de que el sistema distingue las dos ejecuciones de cada
ejercicio:**

- **Diferencias grandes:** de 35° a 55° en el ángulo de rodilla y de 30° a 55° en el tronco.
- **Consistentes:** se repiten en las 3 variantes del modelo y en cada repetición individual. Los
  rangos por repetición de buena y mala técnica **no se superponen**.
- **Fieles a lo que se ve:** la auditoría visual confirma que el esqueleto está bien ubicado en
  los frames medidos.
- **En la dirección que se pedía:** el ángulo de rodilla es **más cerrado en la mala técnica** en
  los dos ejercicios.

| Ejercicio | Bien | Mal | Diferencia (full) |
|---|---|---|---|
| **Salto**, rodilla tras el aterrizaje (ángulo interno mínimo en 300 ms) | 118–125° (flexión ~55–62°) | **66–83°** (flexión ~97–114°) | **~52° más cerrada en la mala** |
| **Salto**, tronco tras el aterrizaje (máx. en 300 ms) | 10–14° | **39–69°** | **~57° más inclinado en la mala** |
| **Sentadilla**, rodilla en el punto más bajo | 104–122° (flexión ~58–76°) | **77–86°** (flexión ~94–103°) | **~40° más cerrada en la mala** |
| **Sentadilla**, tronco en el punto más bajo | **101–112°** (más allá de la horizontal) | 57–62° | El "bien" está **~44° más inclinado** |

**Tres advertencias que cambian cómo usar este resultado. Ninguna se puede omitir:**

1. **"Distingue" no es lo mismo que "detecta el riesgo".** El sistema mide de forma confiable
   *qué cambió* entre las dos ejecuciones. Decidir *cuál es riesgosa* depende del criterio
   clínico, y aquí el criterio previsto en el diseño **daría la respuesta al revés** en los
   saltos. La regla de demostración del backend (`risk = 1 − flexión_máx / 60°`, en
   `jump_analysis_processor.py`) premia la flexión, porque el riesgo clásico de LCA es el
   **aterrizaje rígido**. Pero el "mal" salto de estos videos es lo contrario: un aterrizaje
   **profundo y colapsado hacia adelante**, con mucha flexión. Con esa regla, **el salto mal hecho
   saldría con menos riesgo que el bien hecho.** El modelo de riesgo necesita contemplar más de
   un patrón: rigidez, colapso y tronco, y valgo cuando haya vista frontal.
2. **En las sentadillas, las etiquetas parecen invertidas respecto de la técnica clásica.**
   - `sentadilla_bien_echa` muestra al deportista **doblando el tronco más allá de la horizontal,
     con la cabeza a la altura de las rodillas y las rodillas poco flexionadas**. Es un patrón de
     flexión de cadera y columna ("stoop") que normalmente se considera la ejecución incorrecta.
   - `sentadilla_mal_echa` muestra una sentadilla más erguida y con más flexión de rodilla.

   El sistema separa ambas sin ambigüedad. Pero **hay que confirmar cuál quisiste grabar como
   correcta**: si los nombres son los intencionales, la "buena" no es una sentadilla de manual.
3. **Valgo: sigue sin evaluarse.** Los 4 videos están en vista oblicua; el valgo necesita vista
   frontal. Es la otra mitad del riesgo de LCA y queda pendiente.

**Rastreo con `num_poses=1` (el modo de producción): estable.**
- En 12 corridas, **ningún salto brusco de la cadera** y desplazamiento máximo entre frames de
  0,45 torsos.
- **El espejo nunca se rastreó**, comprobado en todas las grillas de auditoría.
- Frames sin pose: 0 en 3 de los 4 videos. En `salto_mal_echo` son 3–4 (3 %), en huecos de 1 a 3
  frames durante el aterrizaje en cuclillas con los pies al borde del cuadro.

**Recomendación: seguir con MediaPipe, variante `full`** (§6). Antes de construir el dominio de IA
hacen falta tres cosas, en este orden:
1. **Redefinir los criterios de riesgo** por patrón (§7), no sólo "poca flexión = riesgo".
2. **Grabar el par frontal** para el valgo.
3. **Grabar a 30 fps sin reprocesar** y con los pies siempre en cuadro.

## 2. Entorno y método

- **Máquina:** AMD Ryzen 5 4500U (6 núcleos), 7,4 GB de RAM, Windows 11; Python 3.12, mediapipe
  1.0.1, CPU, todos los hilos. **`num_poses=1` en todas las corridas.**
- **Script:** `analyze_real.py`, el de la corrida anterior, con estos cambios:
  - lista de videos nueva y sin la configuración de varias personas;
  - **métrica de estabilidad del rastreo** (§3);
  - **detección de saltos rehecha** (§4.1).

  Igual que antes: un subproceso por video × variante y RSS medido con un hilo de muestreo cada
  5 ms.
- **Ángulos:**
  - **rodilla:** ángulo **interno** 2D cadera–rodilla–tobillo; 180° es la pierna extendida y la
    flexión es 180° − el interno;
  - **tronco:** ángulo cadera→hombro respecto de la vertical; más de 90° significa hombros por
    debajo de la cadera;
  - se mide el lado de mayor visibilidad (aquí siempre el izquierdo).
- **Vista oblicua:** los ángulos 2D en vista oblicua **no son los ángulos anatómicos reales**. Hay
  un error de proyección que depende de cuánto gira la persona respecto de la cámara. Como los
  dos videos de cada par se grabaron con la misma ubicación de cámara, la **comparación** entre
  ellos es válida; los **valores absolutos** no deben leerse como grados clínicos.

## 3. Estabilidad del rastreo con `num_poses=1`

Sin IDs de persona, se buscaron dos firmas de que el rastreo saltó a otra figura, por ejemplo al
reflejo:
- **Saltos bruscos de la cadera:** desplazamiento de más de medio torso entre frames
  consecutivos.
- **Torso encogido:** frames donde el torso mide menos del 60 % de su mediana, porque el reflejo
  está más lejos y se ve más chico.

| video | modelo | frames sin pose | hueco más largo | saltos bruscos de cadera (> 0.5 torso) | frames con torso < 60 % | desplazamiento máx. entre frames |
|---|---|---|---|---|---|---|
| salto_bien_echo | lite | 0 | 0 | 0 | 0 | 0.45 torsos |
| salto_bien_echo | full | 0 | 0 | 0 | 0 | 0.40 torsos |
| salto_bien_echo | heavy | 0 | 0 | 0 | 0 | 0.39 torsos |
| salto_mal_echo | lite | 3 | 1 | 0 | 1 (f1) | 0.31 torsos |
| salto_mal_echo | full | 4 | 3 | 0 | 0 | 0.31 torsos |
| salto_mal_echo | heavy | 3 | 2 | 0 | 2 (f4, f5) | 0.32 torsos |
| sentadilla_bien_echa | lite | 0 | 0 | 0 | 0 | 0.22 torsos |
| sentadilla_bien_echa | full | 0 | 0 | 0 | 0 | 0.23 torsos |
| sentadilla_bien_echa | heavy | 0 | 0 | 0 | 0 | 0.16 torsos |
| sentadilla_mal_echa | lite | 0 | 0 | 0 | 0 | 0.14 torsos |
| sentadilla_mal_echa | full | 0 | 0 | 0 | 0 | 0.11 torsos |
| sentadilla_mal_echa | heavy | 0 | 0 | 0 | 0 | 0.11 torsos |

**Respuesta a la pregunta:** con una sola persona real y `num_poses=1`, **el rastreo es estable
durante todo el clip y no se confunde con el reflejo**. Los pocos frames de "torso encogido" en
`salto_mal_echo` (f1, f4, f5) son el inicio del clip, con la persona inclinada y parcialmente
fuera de cuadro, no el espejo; lo muestra la auditoría. La detección se pierde un instante sólo
cuando los pies salen del cuadro, y se recupera en 1 a 3 frames.

## 4. Resultados por movimiento

### 4.1 Saltos: despegue, aterrizaje y rodilla al aterrizar

**Cómo se detecta cada salto** (rehecho para esta corrida; motivos en §8):
- **Anclaje:** cada salto se ancla en un **ápice de la cadera**, un pico limpio de su trayectoria
  vertical. Ver `output/real/jump_trajectories.png`.
- **Contacto:** desde el ápice, el primer frame en que el **punto más bajo del pie** (el más bajo
  de tobillo, talón y punta) vuelve a su **suelo local**, el percentil 90 en una ventana de ±1 s.
- **Despegue:** el último frame en el suelo antes del ápice.
- **Exclusiones:** no se cuentan los aterrizajes en los últimos 3 frames del clip (los pies
  salieron del cuadro).
- **Métrica:** el **ángulo mínimo de rodilla (máxima flexión) y la inclinación máxima del tronco en
  los 300 ms posteriores al contacto**, es decir, la fase de amortiguación. Es más estable que el
  valor en el frame exacto de contacto, que a 16,6 fps tiene ±60 ms de incertidumbre.

| video | modelo | saltos válidos / detectados | rodilla al contacto (mediana) | **rodilla mín. 300 ms (flexión)** | por salto | **tronco máx. 300 ms** | por salto |
|---|---|---|---|---|---|---|---|
| salto_bien_echo | lite | 6 / 6 | 137° | **125° (55°)** | 136°, 136°, 115°, 113°, 148°, 113° | **10°** | 10°, 1°, 10°, 12°, 3°, 21° |
| salto_bien_echo | full | 6 / 6 | 142° | **118° (62°)** | 127°, 123°, 113°, 113°, 138°, 103° | **10°** | 9°, 4°, 11°, 14°, 5°, 18° |
| salto_bien_echo | heavy | 6 / 6 | 155° | **121° (59°)** | 129°, 133°, 113°, 107°, 147°, 106° | **14°** | 11°, 9°, 13°, 17°, 15°, 20° |
| salto_mal_echo | lite | 4 / 4 | 136° | **83° (97°)** | 89°, 83°, 69°, 84° | **39°** | 36°, 49°, 38°, 41° |
| salto_mal_echo | full | 3 / 4 | 71° | **66° (114°)** | 66°, 71°, 61°, 177° (excluido) | **67°** | 56°, 76°, 67° |
| salto_mal_echo | heavy | 4 / 5 | 95° | **77° (103°)** | 73°, 81°, 65°, 90°, 175° (excluido) | **69°** | 57°, 73°, 68°, 70° |

Lectura:

- **Detección:** las tres variantes encuentran **los mismos saltos**:
  - `salto_bien_echo`: 6 saltos, con ápices en f6–7, 28, 49, 72, 97 y 119;
  - `salto_mal_echo`: 4 saltos, con ápices en f21, 45, 68 y 92-93;
  - los aterrizajes coinciden con ±2 frames.
- **Separación:** **la rodilla nunca se cierra por debajo de 103° en el "bien" y nunca supera 90°
  en el "mal".** Los rangos por salto no se superponen en ninguna variante, y lo mismo pasa con
  el tronco (≤ 21° contra ≥ 36°).
- **Lo que no sirve:** la duración del vuelo **no es confiable**. Sale de 0,5 a 1,2 s porque el
  despegue se marca temprano durante la preparación. No se usa como métrica.
- **Rodilla al contacto:** varía mucho entre variantes en el "mal" (71°, 95°, 136°). A 16,6 fps
  el frame de contacto es impreciso y la rodilla cambia muy rápido. Por eso la métrica es el
  mínimo en 300 ms.

### 4.2 Sentadillas: rodilla en el punto más bajo

Fondo de cada repetición: mínimo local del ángulo de rodilla (prominencia de 25° o más, por debajo
de 130°). Sólo cuentan los fondos con visibilidad de rodilla y tobillo de 0.5 o más.

| video | modelo | reps válidas / detectadas | **rodilla en el fondo (flexión)** | por rep | **tronco en el fondo** | por rep |
|---|---|---|---|---|---|---|
| sentadilla_bien_echa | lite | 4 / 4 | **104° (76°)** | 111°, 97°, 116°, 61° | **102°** | 114°, 106°, 98°, 60° |
| sentadilla_bien_echa | full | 4 / 4 | **117° (63°)** | 121°, 120°, 113°, 94° | **101°** | 115°, 88°, 118°, 72° |
| sentadilla_bien_echa | heavy | 2 / 2 | **122° (58°)** | 120°, 125° | **112°** | 112°, 112° |
| sentadilla_mal_echa | lite | 3 / 3 | **86° (94°)** | 92°, 79°, 86° | **62°** | 62°, 62°, 62° |
| sentadilla_mal_echa | full | 3 / 3 | **77° (103°)** | 82°, 69°, 77° | **57°** | 60°, 57°, 56° |
| sentadilla_mal_echa | heavy | 3 / 3 | **79° (101°)** | 83°, 73°, 79° | **58°** | 63°, 58°, 57° |

Lectura:

- **Separación:** **el "mal" flexiona la rodilla ~40° más y mantiene el tronco ~45° más
  erguido.** Los rangos por repetición no se superponen en full ni en heavy. La única excepción
  es una repetición de lite en el "bien" (61°), un valor atípico de esa variante.
- **Repeticiones detectadas en el "bien":** el video tiene 4 inclinaciones visibles. Full y lite
  encuentran las 4; heavy sólo 2, porque la rodilla apenas baja de 130° (el umbral del detector)
  y heavy la ubica algo más extendida.
- **Talón y rodilla-punta:** no se interpretan. En vista oblicua no tienen el significado que
  tienen en vista lateral; están en `results.json`.

## 5. Rendimiento y calidad de detección

### 5.1 Tiempo y memoria

| video | modelo | carga (s) | ms/frame medio | ms/frame p95 | fps | RSS pico proceso (MB) | RSS del modelo + inferencia (MB) |
|---|---|---|---|---|---|---|---|
| salto_bien_echo | lite | 1.06 | 21.3 | 35.0 | 46.9 | 193 | +163 |
| salto_bien_echo | full | 0.18 | 23.4 | 31.3 | 42.8 | 204 | +174 |
| salto_bien_echo | heavy | 0.26 | 81.3 | 116.4 | 12.3 | 268 | +238 |
| salto_mal_echo | lite | 0.54 | 30.4 | 65.7 | 32.9 | 192 | +162 |
| salto_mal_echo | full | 0.17 | 24.0 | 30.0 | 41.7 | 203 | +173 |
| salto_mal_echo | heavy | 0.29 | 71.5 | 113.1 | 14.0 | 268 | +238 |
| sentadilla_bien_echa | lite | 0.14 | 16.9 | 29.1 | 59.1 | 193 | +163 |
| sentadilla_bien_echa | full | 0.16 | 25.7 | 37.6 | 38.9 | 203 | +173 |
| sentadilla_bien_echa | heavy | 0.24 | 67.0 | 86.2 | 14.9 | 269 | +239 |
| sentadilla_mal_echa | lite | 0.16 | 17.1 | 27.1 | 58.6 | 193 | +163 |
| sentadilla_mal_echa | full | 0.23 | 24.0 | 33.1 | 41.7 | 203 | +173 |
| sentadilla_mal_echa | heavy | 0.23 | 88.9 | 166.1 | 11.2 | 268 | +238 |

- **Tiempos:** lite ~17–30 ms/frame, **full ~23–26 ms/frame**, heavy ~67–89 ms/frame, es decir,
  heavy es unas 3 veces más lento que full.
- **Memoria del proceso:** ~193 / 204 / 268 MB.
- **Coherencia con la corrida anterior:** las cifras coinciden. La variación de heavy (p95 de hasta
  166 ms) es carga de la laptop, no del modelo.
- **Un video de 40 s:** a 30 fps son 1200 frames, que llevarían unos **30 s con full** y unos
  **90–105 s con heavy** en esta máquina. En Cloud Run, con 1–2 vCPU, conviene suponer de 2 a 3
  veces más.

### 5.2 Calidad de detección

| video | modelo | frames con pose | visibilidad cadera (media / p10) | rodilla (media / p10) | tobillo (media / p10) | concordancia rodilla vs heavy (MAE / p90) |
|---|---|---|---|---|---|---|
| salto_bien_echo | lite | 100 % | 1.00 / 1.00 | 0.73 / 0.46 | 0.73 / 0.47 | 4.5° / 10.2° |
| salto_bien_echo | full | 100 % | 1.00 / 0.99 | 0.76 / 0.51 | 0.74 / 0.45 | 3.1° / 6.5° |
| salto_bien_echo | heavy | 100 % | 1.00 / 1.00 | 0.54 / 0.15 | 0.57 / 0.20 | referencia |
| salto_mal_echo | lite | 97 % | 0.98 / 0.96 | 0.64 / 0.34 | 0.58 / 0.28 | 9.4° / 19.8° |
| salto_mal_echo | full | 97 % | 1.00 / 0.99 | 0.65 / 0.30 | 0.57 / 0.28 | 4.7° / 9.9° |
| salto_mal_echo | heavy | 97 % | 1.00 / 0.99 | 0.45 / 0.13 | 0.41 / 0.12 | referencia |
| sentadilla_bien_echa | lite | 100 % | 0.99 / 0.98 | 0.62 / 0.25 | 0.61 / 0.30 | 11.2° / 24.0° |
| sentadilla_bien_echa | full | 100 % | 1.00 / 1.00 | 0.68 / 0.29 | 0.70 / 0.39 | 7.3° / 16.4° |
| sentadilla_bien_echa | heavy | 100 % | 1.00 / 1.00 | 0.45 / 0.06 | 0.51 / 0.12 | referencia |
| sentadilla_mal_echa | lite | 100 % | 1.00 / 1.00 | 0.66 / 0.34 | 0.69 / 0.41 | 7.5° / 12.4° |
| sentadilla_mal_echa | full | 100 % | 1.00 / 1.00 | 0.80 / 0.53 | 0.78 / 0.52 | 2.3° / 4.2° |
| sentadilla_mal_echa | heavy | 100 % | 1.00 / 1.00 | 0.62 / 0.24 | 0.70 / 0.37 | referencia |

- **Variantes:** **full y heavy coinciden de cerca**: 2–7° de diferencia media en la rodilla,
  frente a 13–33° en la corrida con grabaciones de pantalla. Lite se aparta más (4–11°).
- **Auditoría visual:** **en los 4 videos las tres variantes ubican bien cadera, rodilla, tobillo
  y pie**, también en el fondo de la sentadilla y en el aterrizaje en cuclillas. Es la gran
  diferencia con la corrida anterior, donde en esas posturas las piernas colapsaban.
- **La visibilidad sigue sin servir como control de calidad:** heavy marca la rodilla con p10 de
  0.06–0.24 aunque en la auditoría la ubica bien. No conviene descartar frames por visibilidad sin
  una verificación anatómica.

## 6. Recomendación de variante: `full`

| | lite | **full** | heavy |
|---|---|---|---|
| Tiempo/frame | ~17–30 ms | **~23–26 ms** | ~67–89 ms (unas 3 veces full) |
| Memoria | ~193 MB | **~204 MB** | ~268 MB |
| Concordancia con heavy | 4.5–11.2° | **2.3–7.3°** | — |
| Conclusiones bien vs. mal | Las mismas, con más dispersión (una rep atípica de 61°) | **Las mismas** | Las mismas; pierde 2 de 4 reps en la sentadilla "bien" |

**`full`** llega a las mismas conclusiones que heavy, con diferencias de pocos grados, por un
tercio del costo. Heavy no aportó nada que cambie una conclusión. Lite ahorra poco (unos
5 ms/frame) y es la más dispersa.

**Ya no es una recomendación provisional por falta de datos**: con videos reales de buena
calidad, full es la opción razonable. Vale volver a compararlas cuando haya videos a 30 fps y en
vista frontal (valgo).

## 7. Qué significa esto para el dominio de IA

1. **La medición funciona.** Con una sola persona, cámara apoyada y vista constante entre
   repeticiones, MediaPipe `full` mide ángulos de rodilla y tronco que separan sin ambigüedad dos
   ejecuciones distintas. La base del pipeline es viable.
2. **El criterio de riesgo no es una sola regla.** Estos videos mostraron un error que el modelo
   del diseño no contempla: el **aterrizaje colapsado** (mucha flexión y tronco adelantado). Con la
   regla actual ("menos flexión = más riesgo") se clasificaría al revés. Hay que definir
   `RiskScoringStrategy` por patrón, como ya anticipa el diseño en
   `video-analysis-pipeline.md` §5:
   - **rigidez:** flexión mínima insuficiente;
   - **colapso o falta de control:** flexión excesiva junto con un tronco por encima de un umbral;
   - **tronco:** inclinación excesiva;
   - **valgo:** sólo con vista frontal.

   Y hay que validarlas con alguien con formación en biomecánica.
3. **La etiqueta del ejercicio importa.** La sentadilla "bien" de estos videos sería "mal" según
   la técnica clásica. Antes de entrenar o calibrar umbrales, **cada video de referencia necesita
   una etiqueta confirmada por un criterio explícito.**

## 8. Limitaciones y problemas encontrados

1. **16,6 fps y desenfoque.** El contacto con el suelo queda resuelto a unos ±60 ms, y la rodilla
   al contacto exacto no es confiable. La métrica de 300 ms lo mitiga. **Hay que grabar a 30 fps
   o más y evitar reprocesar el video** (por ejemplo, no enviarlo por apps de mensajería).
2. **Vista oblicua.** Los ángulos absolutos tienen error de proyección: la comparación dentro de
   un par es válida, los valores clínicos no. Para la flexión hay que usar **vista lateral
   estricta**, y para el valgo, **vista frontal**.
3. **Pies fuera del cuadro** (`salto_mal_echo`, al final y en algunos aterrizajes). Causa los
   frames sin pose y uno de los eventos espurios, excluido. **Hay que dejar margen bajo los pies.**
4. **El espejo.** Esta vez no causó problemas, pero es una segunda figura humana en cuadro. Con
   otra iluminación o distancia podría hacerlo. **La guía de grabación debería pedir un fondo sin
   espejos ni pantallas.**
5. **Cámara en mano.** El suelo se mueve en la imagen. La detección de saltos necesitó un "suelo
   local" en lugar de uno fijo por clip.
6. **Heurísticas ajustadas sobre estos mismos videos:** el suelo local, el punto más bajo del pie
   y el anclaje en el ápice de la cadera. Se corrigieron porque la versión anterior fallaba de
   forma visible: en el "mal", estar en puntas de pie se confundía con estar en el aire, y la
   persona se acerca a la cámara. Es un riesgo de **sobreajuste**: hay que validarlas con videos
   nuevos que no se usaron para ajustarlas.
7. **Una persona y pocas repeticiones** (4 a 6 por video). Alcanza para ver una separación grande,
   no para estimar el error del sistema ni para fijar umbrales.
8. **Sin datos de referencia.** No hay goniómetro: los grados absolutos no están validados. Sí
   está validado, por auditoría visual, que el esqueleto está donde corresponde.
9. **Detector de repeticiones de sentadilla:** el umbral de 130° hace que heavy pierda
   repeticiones cuando la rodilla flexiona poco. En producción convendría detectar las
   repeticiones por la cadera, como en los saltos, y no por la rodilla.

**Próximo set de videos recomendado:** las mismas condiciones de esta corrida, más estas
correcciones:
- **30 fps sin reprocesar**;
- **un par en vista lateral estricta y otro en vista frontal** de cada ejercicio;
- **pies siempre en cuadro**;
- **fondo sin espejo**;
- **2–3 personas** distintas;
- **la etiqueta bien/mal definida por un criterio escrito**;
- **un ángulo medido a mano por video** para estimar el error en grados.

## 9. Frames anotados y auditoría visual

**Frames clave** (esqueleto completo: lado medido en verde y el otro en naranja; ampliados ×2;
con el ángulo interno de rodilla, la flexión y el tronco escritos encima):

| Video | lite | full | heavy |
|---|---|---|---|
| salto_bien_echo (máx. flexión tras el 1.er aterrizaje) | `output/real/salto_bien_echo/lite/aterrizaje_max_flexion_frame13.png` | `output/real/salto_bien_echo/full/aterrizaje_max_flexion_frame13.png` | `output/real/salto_bien_echo/heavy/aterrizaje_max_flexion_frame13.png` |
| salto_mal_echo (máx. flexión tras el 1.er aterrizaje) | `output/real/salto_mal_echo/lite/aterrizaje_max_flexion_frame28.png` | `output/real/salto_mal_echo/full/aterrizaje_max_flexion_frame29.png` | `output/real/salto_mal_echo/heavy/aterrizaje_max_flexion_frame30.png` |
| sentadilla_bien_echa (fondo más profundo) | `output/real/sentadilla_bien_echa/lite/punto_mas_bajo_frame110.png` | `output/real/sentadilla_bien_echa/full/punto_mas_bajo_frame112.png` | `output/real/sentadilla_bien_echa/heavy/punto_mas_bajo_frame9.png` |
| sentadilla_mal_echa (fondo más profundo) | `output/real/sentadilla_mal_echa/lite/punto_mas_bajo_frame51.png` | `output/real/sentadilla_mal_echa/full/punto_mas_bajo_frame51.png` | `output/real/sentadilla_mal_echa/heavy/punto_mas_bajo_frame53.png` |

Los 4 frames clave de full lado a lado: `output/real/key_frames_full.jpg`.

**Auditoría visual** (10 frames repartidos × 3 variantes por video, con pie completo):
- `output/real/audit/salto_bien_echo.jpg`
- `output/real/audit/salto_mal_echo.jpg`
- `output/real/audit/sentadilla_bien_echa.jpg`
- `output/real/audit/sentadilla_mal_echa.jpg`

Grillas densas de un salto completo (frame por medio, full):
- `output/real/audit/salto_bien_echo_salto2_denso.jpg`
- `output/real/audit/salto_mal_echo_salto1_denso.jpg`

Trayectorias de pies, cadera y hombros, con los saltos marcados:
`output/real/jump_trajectories.png`. Muestra la versión anterior de la detección; ver §8.6.

Datos crudos: `output/real/results.json` y `output/real/<video>/<variante>/{landmarks.npz,perf.json}`.

## 10. Cómo reproducir

```bash
cd backend/spikes/pose_spike
.venv-spike\Scripts\activate                 # Windows (ver README para crearlo)
python test_spike.py                         # auto-chequeo: 9/9
python analyze_real.py                       # 12 extracciones (num_poses=1) + análisis
python analyze_real.py analyze               # sólo re-analizar landmarks ya extraídos
```

Para otro set de videos, cambiar `VIDEOS` en `analyze_real.py` (nombre → movimiento y vista).

---

# Anexo A — corrida con grabaciones de pantalla (2026-10-01, primera corrida)

> **Reemplazado por la corrida principal en:** calidad de detección, comparación bien vs. mal y
> recomendación de variante. Esta corrida no podía concluir nada porque los videos eran
> grabaciones de pantalla de redes sociales, con varias personas y vistas no comparables. Siguen
> vigentes como aprendizaje: las limitaciones de §8 (varias personas en cuadro, la visibilidad no
> sirve como control de calidad) y el protocolo de grabación. Sus resultados se movieron a
> `output/real_pantalla/` y `output/contact_pantalla/`; las rutas de abajo ya están actualizadas.

### Veredicto

**Con estos 4 videos, el sistema no demuestra que pueda distinguir una técnica riesgosa de una
segura.** No es una conclusión sobre MediaPipe en general: es una conclusión sobre estos datos.

1. **Los 4 videos son grabaciones de una pantalla** (celular apuntando a una computadora o a otro
   celular que reproduce videos de redes sociales):
   - moiré, desenfoque y **doble exposición** (frames mezclados);
   - interfaz superpuesta: "Suscribirse", buscador, subtítulos, ícono de *play*, una X roja, la
     barra de tareas de Windows;
   - cortes de escena y cambios de zoom;
   - resolución efectiva baja (474×850).

   Ninguno se parece a lo que va a grabar la app.
2. **Los dos saltos no son comparables entre sí.** "Buena técnica" es una recopilación de saltos
   pliométricos verticales **vistos de frente**. "Mala técnica" es un **salto horizontal** de otra
   persona **visto de costado**, con un entrenador y otras personas en cuadro. Cambian el
   movimiento, la vista, la persona y el error que se corrige (apoyo en talón vs. punta, no
   valgo).
3. **En el salto de mala técnica, MediaPipe rastrea a la persona equivocada** (el entrenador, que
   está de pie). Con varias poses y seguimiento por cercanía, en algunos frames llega a producir
   **una pose fusionada entre dos personas** (un lado del esqueleto en cada una). El análisis de
   ese video no es utilizable.
4. **En las sentadillas (el único par comparable: misma persona, mismo ejercicio, vista
   lateral), la detección de piernas falla justamente en el punto más bajo.** Rodillas y tobillos
   colapsan sobre el muslo en muchos de los frames que hay que medir. La visibilidad que reporta
   MediaPipe **no** detecta esos errores: hay frames con piernas mal ubicadas y visibilidad ≥ 0.5.
5. **La única diferencia robusta entre buena y mala sentadilla es la inclinación del tronco:**
   unos 40° en la mala contra 10–23° en la buena, en las 3 variantes, y en la dirección esperada.
   Se apoya en hombros y caderas, que se detectan bien (visibilidad ~1.0). Las diferencias de
   ángulo de rodilla, talón levantado y rodilla adelantada **sí van en la dirección esperada**,
   pero se miden sobre piernas mal ubicadas, así que **no se pueden tomar como evidencia**.
6. **Valgo: no se pudo evaluar.** Sólo hay un video frontal (el salto de buena técnica, sin su
   par de mala técnica frontal), y sus "aterrizajes" caen en frames con doble exposición donde las
   piernas no se distinguen.

**Recomendación:** no construir todavía el dominio de IA sobre estos resultados. Antes, grabar
**un set mínimo de videos propios con el protocolo de §8** (unos 30 minutos de trabajo) y volver a
correr `analyze_real.py`. Lo que sí quedó demostrado es que **el costo de cómputo es viable** y
que **la parte superior del cuerpo se detecta de forma estable**.

### 1. Videos analizados

| Video | Movimiento real | Vista | Personas | Problemas observados |
|---|---|---|---|---|
| `salto_buena_tecnica.mp4` | Recopilación de saltos pliométricos (sobre caja y laterales, "3x5/lado") | **Frontal** | 1 | Grabación de pantalla, doble exposición, ícono de *play* superpuesto, **corte de escena en f64**, cambio de gimnasio |
| `salto_mala_tecnica.mp4` | **Salto horizontal** con corrección del entrenador | **Lateral/oblicua** | **3+** (deportista, entrenador, gente al fondo) | Grabación de pantalla, subtítulos, barra de tareas de Windows, las personas se superponen |
| `sentadillas_buena_tecnica.mp4` | Sentadilla goblet, varias repeticiones | Lateral / 3⁄4 | 1 | Grabación de pantalla, texto superpuesto, corte en f71, cambios de zoom |
| `sentadillas_mala_tecnica.mp4` | Sentadilla goblet; error marcado: **talón levantado** y trayectoria diagonal | Lateral | 1 | Grabación de pantalla, X roja superpuesta junto a los pies |

Todos: 474×850 en vertical, unos 25 fps, entre 3,7 y 12,6 s. `synthetic_smoke.mp4` se ignoró.

Hojas de contacto (8 frames por video, para ver de qué se trata cada uno):
`output/contact_pantalla/<video>.jpg`.

### 2. Entorno y método

- **Máquina:** AMD Ryzen 5 4500U (6 núcleos), 7,4 GB de RAM, Windows 11, sin Docker; Python 3.12,
  mediapipe 1.0.1, CPU, todos los hilos disponibles. No es Cloud Run: ver §6.
- **Script:** `analyze_real.py`, desechable, dentro del spike. Reutiliza `spike/landmarker.py`,
  `spike/video_source.py` y `spike/smoothing.py`; no toca `run_spike.py` ni el pipeline.
  - Un **subproceso por video × variante**: la memoria de un modelo no contamina la medición del
    siguiente.
  - RSS pico medido con un **hilo de muestreo cada 5 ms**, no una lectura por frame como el
    reporte anterior.
  - Resolución original, stride 1, `num_poses=1`. Excepción: `salto_mala` con `num_poses=3` y
    seguimiento (§4.2).
- **Ángulo de rodilla:** es el **ángulo interno** cadera–rodilla–tobillo en 2D (180° = pierna
  extendida). La flexión es 180° − el interno. `spike/angles.py` lo llama `knee_flexion_deg`,
  pero lo que calcula es el ángulo interno; el nombre confunde.
- **Calidad sin datos de referencia:** no hay goniómetro ni anotación manual. La calidad se
  estimó de tres formas:
  - la visibilidad que reporta MediaPipe;
  - la concordancia entre variantes;
  - una **auditoría visual** de 8 frames anotados por video × variante
    (`output/real_pantalla/audit/*.jpg`). Fue la más informativa.

### 3. Rendimiento por variante (tiempo y memoria reales)

| video | modelo | carga (s) | ms/frame medio | ms/frame p95 | fps | RSS pico proceso (MB) | RSS del modelo + inferencia (MB) |
|---|---|---|---|---|---|---|---|
| salto_buena_tecnica | lite | 0.31 | 22.6 | 39.6 | 44.2 | 193 | +163 |
| salto_buena_tecnica | full | 0.25 | 27.7 | 46.6 | 36.2 | 203 | +173 |
| salto_buena_tecnica | heavy | 0.36 | 66.1 | 91.2 | 15.1 | 268 | +238 |
| salto_mala_tecnica\* | lite | 0.42 | 37.6 | 42.3 | 26.6 | 192 | +162 |
| salto_mala_tecnica\* | full | 0.23 | 42.7 | 51.8 | 23.4 | 203 | +173 |
| salto_mala_tecnica\* | heavy | 0.22 | 73.1 | 80.5 | 13.7 | 269 | +238 |
| sentadillas_buena_tecnica | lite | 0.14 | 14.6 | 16.6 | 68.5 | 194 | +164 |
| sentadillas_buena_tecnica | full | 0.33 | 23.0 | 29.3 | 43.5 | 206 | +176 |
| sentadillas_buena_tecnica | heavy | 0.21 | 65.7 | 78.9 | 15.2 | 270 | +240 |
| sentadillas_mala_tecnica | lite | 0.13 | 14.3 | 16.2 | 70.0 | 195 | +165 |
| sentadillas_mala_tecnica | full | 0.15 | 20.4 | 23.7 | 49.1 | 206 | +176 |
| sentadillas_mala_tecnica | heavy | 0.28 | 63.1 | 84.1 | 15.9 | 269 | +239 |

\* `salto_mala` con `num_poses=3`. Con `num_poses=1` (primera corrida) fue 15,9 / 29,6 / 77,7
ms/frame para lite / full / heavy. Detectar varias personas cuesta más tiempo en lite y full.

Resumen, con una persona en cuadro:
- **lite** ≈ 15–23 ms/frame; **full** ≈ 20–30 ms/frame; **heavy** ≈ 63–78 ms/frame. **Heavy es
  unas 3 veces más lento que full.**
- **Memoria:** +165 / +175 / +240 MB respectivamente. El proceso completo queda en unos
  195 / 205 / 270 MB. Carga del modelo: menos de 0,5 s en los tres.
- **Un video de 40 s** (el límite de producto, unos 1000 frames a 25 fps) tardaría en esta
  máquina unos **15–23 s con lite, 20–30 s con full y 63–78 s con heavy**. En Cloud Run, con 1–2
  vCPU, conviene suponer de 2 a 3 veces más.

El reporte anterior medía tiempos casi iguales entre variantes porque el video sintético no tenía
persona y nunca se ejecutaba la red de landmarks. **Esa conclusión queda reemplazada por esta
tabla.**

### 4. Calidad de detección

| video | modelo | frames con pose | visibilidad cadera (media / p10) | rodilla (media / p10) | tobillo (media / p10) | concordancia rodilla vs heavy (MAE / p90) |
|---|---|---|---|---|---|---|
| salto_buena_tecnica | lite | 91 % | 1.00 / 0.99 | 0.61 / 0.48 | 0.49 / 0.37 | 7.1° / 13.8° |
| salto_buena_tecnica | full | 80 % | 1.00 / 0.99 | 0.63 / 0.55 | 0.53 / 0.41 | 9.3° / 14.4° |
| salto_buena_tecnica | heavy | 94 % | 1.00 / 1.00 | 0.38 / 0.21 | 0.37 / 0.21 | referencia |
| salto_mala_tecnica | lite | 100 % | 1.00 / 1.00 | 0.81 / 0.46 | 0.86 / 0.65 | 11.3° / 25.9° |
| salto_mala_tecnica | full | 98 % | 1.00 / 0.99 | 0.76 / 0.38 | 0.80 / 0.46 | 9.1° / 18.8° |
| salto_mala_tecnica | heavy | 99 % | 1.00 / 1.00 | 0.62 / 0.14 | 0.77 / 0.44 | referencia |
| sentadillas_buena_tecnica | lite | 99 % | 1.00 / 1.00 | 0.78 / 0.56 | 0.69 / 0.49 | 32.7° / 87.9° |
| sentadillas_buena_tecnica | full | 98 % | 1.00 / 1.00 | 0.72 / 0.47 | 0.65 / 0.35 | 13.8° / 25.0° |
| sentadillas_buena_tecnica | heavy | 100 % | 1.00 / 1.00 | 0.51 / 0.08 | 0.52 / 0.10 | referencia |
| sentadillas_mala_tecnica | lite | 100 % | 1.00 / 1.00 | 0.69 / 0.33 | 0.72 / 0.44 | 13.4° / 33.7° |
| sentadillas_mala_tecnica | full | 100 % | 1.00 / 1.00 | 0.62 / 0.27 | 0.62 / 0.26 | 8.5° / 20.2° |
| sentadillas_mala_tecnica | heavy | 100 % | 1.00 / 1.00 | 0.38 / 0.03 | 0.46 / 0.07 | referencia |

Cómo leer esta tabla:

- **"Frames con pose" es engañoso.** Un 98–100 % sólo dice que hubo *alguna* pose, no que sea la
  persona correcta ni que las piernas estén bien ubicadas. En `salto_mala` hay un 100 %, pero es
  sobre el entrenador.
- **Caderas: visibilidad ~1.0 en todo.** La parte superior del cuerpo se detecta de forma estable.
- **Rodillas y tobillos: visibilidad media a baja, y muy baja en heavy** (p10 = 0.03–0.21). Heavy
  marca como dudosas las piernas que no ve bien, mientras que lite y full les asignan más
  "confianza" aunque estén igual de mal ubicadas.
- **La concordancia no mide precisión.** Que dos variantes coincidan no dice que alguna acierte.
  Aun así, full queda más cerca de heavy que lite en las sentadillas, donde lite discrepa hasta
  88° en el percentil 90.

**Auditoría visual** (`output/real_pantalla/audit/`):

| Video | Qué se ve |
|---|---|
| `sentadillas_buena_tecnica` | De pie, las 3 variantes ubican bien las piernas. En el fondo de la sentadilla, la pierna **cercana** suele estar bien con full y heavy; la **lejana** colapsa o se cruza. Lite es la más errática. |
| `sentadillas_mala_tecnica` | En el fondo de la sentadilla **las dos piernas colapsan sobre el muslo** en varios frames, con las 3 variantes (por ejemplo, full en f148 y heavy en f269: las "rodillas" y los "tobillos" quedan a la altura de la cadera). De pie está bien. |
| `salto_buena_tecnica` | Siluetas borrosas por la doble exposición; las piernas salen como líneas casi rectas. No se puede validar a ojo dónde están las rodillas. |
| `salto_mala_tecnica` | Con 1 pose sigue al **entrenador**. Con 3 poses y seguimiento salta entre personas y en algunos frames **fusiona** dos personas en un esqueleto (`audit/salto_mala_tecnica_tracking.jpg`). |

### 5. Resultados por movimiento

#### 5.1 Saltos: despegue, aterrizaje y rodilla en el aterrizaje

**Cómo se detectan:** por la trayectoria de los **tobillos**, no de la cadera, porque en el
contramovimiento la cadera baja antes de despegar. El suelo es el percentil 85 de la altura del
tobillo en cada segmento entre cortes. Hay vuelo cuando los dos tobillos suben más de un 6 % de
la altura del cuerpo durante 3 frames o más. Se mide:
- el ángulo interno de la rodilla al contacto y su mínimo en los 300 ms siguientes;
- en vista frontal, además, el **FPPA** (ángulo de proyección en el plano frontal), positivo si
  la rodilla va hacia adentro (valgo).

`salto_buena_tecnica` (vista frontal):

| modelo | despegue → aterrizaje (frames) | vuelo | rodilla interna al contacto | mín. 300 ms | FPPA izq / der al contacto | máx. valgo 300 ms |
|---|---|---|---|---|---|---|
| lite | 35 → 48 | 522 ms | 172° | 172° | +8° / −4° | +8° |
| lite | 100 → 134 | 1365 ms | 173° | 173° | −7° / −2° | +6° |
| full | 34 → 48 | 562 ms | 179° | 156° | +4° / +1° | +7° |
| full | 100 → 112 | 482 ms | 171° | 170° | −6° / +9° | +9° |
| full | (3 eventos más, incluido uno sin landmarks válidos al contacto) | | | | | |
| heavy | 15 → 19 | 161 ms | 171° | 169° | −9° / −8° | −2° |
| heavy | 101 → 112 | 442 ms | 156° | **91°** | −24° / −10° | −4° |
| heavy | 114 → 126 | 482 ms | 165° | 158° | −15° / −9° | +6° |

Lectura:

- **Las tres variantes no coinciden** en cuántos saltos hay ni dónde están.
- **Hay vuelos físicamente imposibles:** 1,4 s con lite.
- **La "rodilla al contacto" de unos 170–179° no significa poca flexión.** En vista frontal la
  flexión de rodilla casi no se ve en 2D.
- **Los FPPA de ±10° están dentro del ruido** de un video con doble exposición. El −24° de heavy
  coincide con un frame mal detectado.

**No se puede afirmar nada sobre el valgo con este video.**

`salto_mala_tecnica` (lateral):
- **Con 1 pose no se detectó ningún salto,** porque se rastreó al entrenador, que está quieto.
- **Con 3 poses y seguimiento,** lite y full "detectan" un salto en f45→49 y f36→42, con la
  rodilla al contacto en 160° y 150°. Pero la auditoría muestra que en esos frames el esqueleto
  ya saltó a otra persona o se fusionó. El vuelo real de la deportista ocurre alrededor de
  f14–f24.
- **Heavy no detecta ninguno.**

**Resultado no utilizable.**

#### 5.2 Sentadillas: rodilla en el punto más bajo

**Cómo se detectan:** el fondo de cada repetición es un mínimo local del ángulo interno de rodilla
(prominencia mayor o igual a 25° y por debajo de 130°). Sólo se cuentan los fondos con visibilidad
de rodilla y tobillo de al menos 0.5. Además del ángulo se mide:
- **tronco:** inclinación respecto de la vertical;
- **talón relativo:** cuánto más alto está el talón que la punta del pie, comparado con la postura
  de pie del mismo video. Así se quita el sesgo de perspectiva. Está en largos de pierna (rodilla
  a tobillo).
- **rodilla-punta:** cuánto pasa la rodilla por delante de la punta del pie, también en largos de
  pierna.

Valores son medianas sobre las repeticiones válidas:

| video | modelo | reps válidas / detectadas | rodilla interna (flexión) | tronco | talón relativo | rodilla-punta |
|---|---|---|---|---|---|---|
| buena | lite | 7 / 7 | 75° (105°) | 10° | +0.21 | +0.08 |
| buena | full | 4 / 4 | 58° (122°) | 19° | +0.07 | +0.12 |
| buena | heavy | 1 / 1 | 45° (135°) | 22° | +0.06 | +0.25 |
| mala | lite | 2 / 2 | 49° (131°) | 40° | +0.38 | +0.70 |
| mala | full | 2 / 2 | 37° (143°) | 40° | +0.30 | +0.70 |
| mala | heavy | 3 / 3 | **21° (159°)** | 41° | +0.29 | +0.91 |

Lectura:

- **Rodilla:** en buena técnica, 45–58° de ángulo interno con full y heavy es plausible para una
  goblet profunda, y en el frame anotado de heavy (f196) la pierna cercana está bien. En mala
  técnica, **21° y 37° son anatómicamente imposibles o casi**: vienen de las piernas colapsadas.
  **La rodilla en mala técnica no es una medición válida.**
- **Variación entre variantes:** la cantidad de repeticiones detectadas va de 1 a 7 según la
  variante. El detector de repeticiones depende directamente de que la rodilla esté bien ubicada.

### 6. Comparación buena vs. mala técnica (la pregunta central)

| Métrica | ¿Diferencia? | ¿En la dirección esperada? | ¿Es confiable? |
|---|---|---|---|
| **Sentadilla, inclinación del tronco** | Sí: unos **40°** en la mala contra 10–23° en la buena, en las 3 variantes | Sí: la trayectoria diagonal y el talón levantado se compensan inclinando el tronco | **Sí**, razonablemente. Usa hombros y caderas (visibilidad ~1.0) y es estable entre variantes. |
| Sentadilla, talón levantado (relativo) | Sí: +0.29 a +0.38 contra +0.06 a +0.21 | Sí: es justo el error que marca el video | **No.** El talón se mide sobre piernas que la auditoría muestra mal ubicadas en el fondo. |
| Sentadilla, rodilla adelantada | Sí: +0.70 a +0.91 contra +0.08 a +0.25 | Sí: trayectoria diagonal | **No.** Si la rodilla colapsa sobre el muslo, queda "adelante" por error. |
| Sentadilla, ángulo de rodilla en el fondo | Sí: la mala sale más "profunda" | No necesariamente: el error del video no es la profundidad | **No.** Los valores de la mala técnica (21–37°) son artefactos. |
| Salto, rodilla al aterrizar | No comparable | — | **No.** Movimiento, vista y persona distintos; en la mala técnica se rastreó a otra persona. |
| Salto, valgo (FPPA) | No evaluable | — | **No.** Hay un solo video frontal y su detección es dudosa. |

**Respuesta honesta:** con estos videos **no hay prueba** de que el sistema distinga técnica
riesgosa de técnica segura.

Lo que hay:
- **Una señal real y robusta:** la inclinación del tronco en la sentadilla.
- **Indicios en la dirección correcta** (talón, rodilla adelantada), que hoy no se pueden separar
  de los errores de detección.

Tampoco hay prueba de lo contrario. **La mayor parte de las fallas se explica por el material de
entrada** (grabación de pantalla, varias personas, cortes, vista inadecuada), no necesariamente
por MediaPipe.

### 7. Recomendación de variante

**Recomendación provisional: `full`.** Justificación:

| | lite | full | heavy |
|---|---|---|---|
| Tiempo por frame | ~15–23 ms | ~20–30 ms | ~63–78 ms (unas 3 veces full) |
| Memoria (proceso) | ~195 MB | ~205 MB | ~270 MB |
| Calidad observada en piernas | La peor: erráticas en la sentadilla buena; MAE de 33° y p90 de 88° contra heavy | Similar a heavy en la auditoría; cercana a heavy (MAE 8.5–13.8°) | **No fue visiblemente mejor** en estos videos: también colapsa en el fondo de la sentadilla mala, y su baja visibilidad en piernas descarta más datos |

- **Heavy** cuesta unas 3 veces más CPU que full (40 s de video: más de 1 minuto en esta
  laptop, y más en Cloud Run) **sin una mejora de calidad demostrada**.
- **Lite** ahorra poco frente a full (unos 5–10 ms/frame) y es claramente la peor en piernas.

**Esta recomendación es provisional.** Con material de mala calidad, las tres variantes fallan
por lo mismo. La comparación lite/full/heavy hay que repetirla con videos grabados con el
protocolo de §8, porque **ahí sí podría aparecer la ventaja de heavy**. Si con buenos videos
heavy acierta claramente más en rodillas y tobillos, su costo puede valer la pena: la Fase 0.5 de
Cloud Run se dimensiona con estos tiempos.

### 8. Limitaciones y qué hace falta

**Limitaciones encontradas:**

1. **Material de entrada:** grabaciones de pantalla con moiré, doble exposición, interfaz y textos
   superpuestos, compresión doble y baja resolución efectiva. Es la causa principal.
2. **Varias personas en cuadro:** MediaPipe no da identidad de persona entre frames. Con
   `num_poses=1` elige a la más visible, no a la que salta. Con varias poses las mezcla cuando se
   superponen. **En producción hay que exigir una sola persona en cuadro** (guía de grabación) o
   agregar un rastreador de identidad.
3. **Vista de cámara:** la flexión de rodilla sólo se mide bien en vista lateral y el valgo sólo
   en vista frontal. Ningún par buena/mala comparte la vista adecuada para el valgo. Esto ya
   estaba previsto en el diseño (`camera_view`, §5 del pipeline).
4. **Oclusión de la pierna lejana en vista lateral:** está en ambas sentadillas. Hay que medir
   **sólo la pierna cercana a la cámara** y descartar la otra.
5. **Fondo de la sentadilla:** es la postura que peor detecta MediaPipe aquí: muslos horizontales
   y piernas plegadas. Es justo el momento que se necesita medir. **Es el riesgo técnico más
   importante para el diseño**, y hay que confirmarlo con buenos videos.
6. **La visibilidad no sirve como control de calidad.** Hubo piernas mal ubicadas con visibilidad
   de 0.5 o más. Hacen falta **verificaciones anatómicas**: longitudes de muslo y pierna estables
   entre frames, tobillo debajo de la rodilla, coherencia temporal.
7. **Cortes de escena:** el detector necesitó un umbral de 0.8, no 0.6, porque grabar la pantalla
   suaviza los cortes. Con videos propios de un solo plano no debería hacer falta.
8. **Sin datos de referencia:** no hay goniómetro ni anotación manual. Aunque los videos fueran
   buenos, falta al menos **una medición de referencia por video** para estimar el error en
   grados.

**Sí, hacen falta más videos y mejores condiciones antes de confiar en este enfoque.** Set mínimo
propuesto, unos 30 minutos de grabación:

| Requisito | Por qué |
|---|---|
| **Grabados directamente con el celular**, no de una pantalla; 1080p o 720p a 30 fps o más | Quita el moiré, la doble exposición y la interfaz |
| **Una sola persona en cuadro**, de cuerpo completo (pies incluidos), cámara fija sobre trípode o apoyo, a la altura de la cadera, a 3–4 m | Evita el problema de identidad y el desenfoque por movimiento de la cámara |
| **Vista lateral** para flexión de rodilla y tronco; **vista frontal** para valgo; **el mismo par buena/mala en la misma vista** | Hace comparables las métricas |
| La **misma persona** ejecutando buena y mala técnica a propósito (por ejemplo, aterrizaje rígido vs. amortiguado; rodillas hacia adentro vs. alineadas), **3–5 repeticiones de cada una** | Aísla la variable técnica de la persona y el entorno |
| Ropa ajustada que contraste con el fondo; buena luz | Mejora la detección de rodillas y tobillos |
| **Un ángulo de referencia** medido a mano con un goniómetro o sobre el frame congelado (con una herramienta de medición en la imagen) en al menos 2 frames por video | Permite reportar el error en grados, no sólo la concordancia |

Con eso, volver a correr `python analyze_real.py` (después de ajustar `VIDEOS` a los nombres
nuevos) responde de verdad las preguntas de este spike.

### 9. Frames anotados para revisión visual

Esqueleto completo: hombro, cadera, rodilla, tobillo, talón y punta del pie. El lado medido va en
verde y el otro en naranja. Cada frame lleva escritos el ángulo interno de rodilla, la flexión, el
tronco y, según el caso, el FPPA o las métricas de talón y rodilla. Los frames están ampliados ×2.

Momento clave (aterrizaje para el salto, punto más bajo para la sentadilla):

- `output/real_pantalla/salto_buena_tecnica/lite/aterrizaje_frame48.png`
- `output/real_pantalla/salto_buena_tecnica/full/aterrizaje_frame48.png`
- `output/real_pantalla/salto_buena_tecnica/heavy/aterrizaje_frame19.png`
- `output/real_pantalla/salto_mala_tecnica/lite/aterrizaje_frame49.png` (persona incorrecta o fusionada: ver §5.1)
- `output/real_pantalla/salto_mala_tecnica/full/aterrizaje_frame42.png` (ídem)
- heavy no detectó ningún salto en `salto_mala_tecnica`, así que no tiene frame clave.
- `output/real_pantalla/sentadillas_buena_tecnica/lite/punto_mas_bajo_frame21.png`
- `output/real_pantalla/sentadillas_buena_tecnica/full/punto_mas_bajo_frame46.png`
- `output/real_pantalla/sentadillas_buena_tecnica/heavy/punto_mas_bajo_frame196.png` (pierna cercana bien ubicada)
- `output/real_pantalla/sentadillas_mala_tecnica/lite/punto_mas_bajo_frame269.png`
- `output/real_pantalla/sentadillas_mala_tecnica/full/punto_mas_bajo_frame148.png` (piernas colapsadas)
- `output/real_pantalla/sentadillas_mala_tecnica/heavy/punto_mas_bajo_frame269.png` (piernas colapsadas)

Auditoría (grillas de 8 frames × 3 variantes por video):
- `output/real_pantalla/audit/salto_buena_tecnica.jpg`
- `output/real_pantalla/audit/salto_mala_tecnica.jpg` (1 pose: sigue al entrenador)
- `output/real_pantalla/audit/salto_mala_tecnica_tracking.jpg` (3 poses con seguimiento: salta entre personas y las fusiona)
- `output/real_pantalla/audit/sentadillas_buena_tecnica.jpg`
- `output/real_pantalla/audit/sentadillas_mala_tecnica.jpg`

Datos crudos: `output/real_pantalla/results.json` y `output/real_pantalla/<video>/<variante>/{landmarks.npz,perf.json}`.

### 10. Cómo reproducir

```bash
cd backend/spikes/pose_spike
python -m venv .venv-spike && .venv-spike\Scripts\activate      # Windows
pip install -r requirements-spike.txt                           # (modelos en models/, ver README)
python test_spike.py                                            # auto-chequeo: 9/9
python analyze_real.py                                          # 12 extracciones + análisis
python analyze_real.py analyze                                  # sólo re-analizar landmarks ya extraídos
```

`output/`, `videos/`, `models/` y `.venv-spike/` están ignorados por git.

---

# Anexo B — corrida con video sintético (2026-09-20)

> **Reemplazado por la corrida principal y el Anexo A en:** (a) costo por variante, que antes era casi
> igual porque no había persona y ahora está medido en §3; (e) confiabilidad de fases y ángulos,
> ahora en §5 y §6. Siguen vigentes como referencia: la corrida de concurrencia en Docker, que no
> se repitió, y lo dicho sobre tamaño de video, que no se midió con material propio. El texto se
> conserva sin cambios.

### Resumen

Se construyo el toolkit completo del spike (`backend/spikes/pose_spike/`) y se
verifico que corre de punta a punta: carga de modelo, deteccion en modo
VIDEO, calculo de angulos, suavizado, deteccion de fases, anotacion de
frames, graficos y tabla de resultados.

**Limitacion central de este informe:** no hubo ningun video real de un
salto (ni de una persona) disponible en este entorno para correr el spike.
Por eso las preguntas que mas importan al diseno — calidad de deteccion,
confiabilidad de la deteccion de fases, precision de los angulos, tamano
tipico de un video grabado — **no se pudieron medir con datos reales** y se
marcan explicitamente como pendientes mas abajo. Lo que si se pudo medir
(costo de inferencia, memoria, tiempo de carga, mecanica de concurrencia) se
hizo con un video sintetico (ruido aleatorio con texto, sin persona) que solo
sirve para ejercitar el codigo, no para representar biomecanica real.

### Que se hizo

1. Implementado el toolkit completo: `video_source`, `landmarker`, `timing`,
   `angles`, `smoothing`, `phases`, `quality`, `annotate`, `plotting`,
   `pipeline`, `report`, mas `run_spike.py` (CLI, todos los parametros
   configurables, ver `--help`) y `test_spike.py` (auto-chequeo).
2. `test_spike.py`: 9 chequeos sobre datos sinteticos controlados (angulos
   conocidos, interpolacion, reduccion de ruido por suavizado, deteccion de
   fases sobre una trayectoria de salto sintetica y sobre una plana sin
   salto). **Los 9 pasan.** Esto valida la logica matematica (angulos,
   suavizado, deteccion de despegue/apice/aterrizaje), independientemente de
   si MediaPipe detecta o no una persona real.
3. Prueba de humo de punta a punta con un video sintetico (1280x720, 150
   frames, ruido aleatorio, sin persona) contra los 3 `.task` reales (lite,
   full, heavy) descargados de la fuente oficial de Google, cruzando
   resolucion (`original`, `480`) y stride (`1`, `2`): 12 combinaciones,
   todas corrieron sin errores y generaron su `series.png` y su fila en
   `output/run_summary.md`.
4. Se descargaron y documentaron en el README las 3 variantes del modelo
   (lite ~5.5 MB, full ~9 MB, heavy ~29 MB) desde
   `storage.googleapis.com/mediapipe-models/...`.
5. Se construyo el `Dockerfile` (con las librerias nativas que mediapipe
   necesita en tiempo de ejecucion, `libgl1`/`libegl1`/`libgles2`, no
   documentadas por mediapipe) y se corrio contenedorizado a 2 vCPU / 3 GB
   (`docker run --cpus=2 --memory=3g`) para simular el VPS objetivo.
6. Se corrio con 2 procesos en paralelo, primero con margen de CPU y luego
   pineados a los mismos 2 nucleos fisicos (`--cpuset-cpus`), para observar
   degradacion por contencion real.

(Ver seccion "Corrida de concurrencia" mas abajo para el detalle: el
mecanismo de simulacion funciona, pero el numero exacto de degradacion
medido en esta laptop tiene baja confianza — ver la lectura honesta ahi.)

### Entorno de medicion

Maquina de desarrollo (Windows, WSL2/Docker Desktop), **no** el VPS de
destino:

- CPU: AMD Ryzen 5 4500U (6 nucleos fisicos), sin garantia de aislamiento de
  otros procesos del sistema mientras se midio.
- mediapipe 1.0.1, Python 3.11 (contenedor) / 3.14 (venv de host, solo para
  el smoke test fuera de Docker).
- Video de prueba: sintetico, 1280x720, 150 frames a 30 fps (~5 s), sin
  persona.

Estos numeros son un piso de referencia (orden de magnitud de esta laptop),
no un reemplazo de medir en el VPS real ni con video real.

### (a) Variante de modelo — lite / full / heavy

| modelo | carga (s) | t medio/frame (ms)* | RSS pico (MB) |
|---|---|---|---|
| lite  | 0.17–0.46 | ~14–23 | ~246–261 |
| full  | 0.12–0.13 | ~16–19 | ~269–277 |
| heavy | 0.17–0.74 | ~15–17 | ~337–344 |

\* medido sobre el video sintetico sin persona.

**Senal real:** el tiempo de carga y el RSS pico crecen con el tamano del
modelo (lite < full < heavy), como se esperaba — es memoria de pesos, no
depende del contenido del video.

**No confiable:** el tiempo por frame es casi identico entre las 3
variantes. Esto casi seguro es un artefacto de que, al no detectar ninguna
persona, el pipeline interno de MediaPipe corta despues de la etapa de
deteccion (mas liviana y compartida) y **nunca llega a correr la red de
landmarks** (que es la que cambia de tamano entre lite/full/heavy). Es decir:
este spike no midio el costo real de "lite vs. full vs. heavy" porque nunca
ejercito la parte que las distingue. Con video real, se espera que la
diferencia de tiempo por frame entre variantes sea mucho mayor que la medida
aqui.

**Recomendacion (parcial, a confirmar con video real):** por RSS y tiempo de
carga, `lite` es la opcion mas barata para un VPS de 3-4 GB; `heavy` casi
duplica el RSS de `lite`. Pero la decision final de variante depende de la
calidad de deteccion real (visibilidad de rodilla/cadera/tobillo, ruido de
la serie), que no se pudo medir aqui. Sugerido: correr este mismo spike con
2-3 videos reales de saltos y comparar `pct_sin_pose` y el ruido antes/despues
de suavizar (columnas de `output/run_summary.md`) entre las 3 variantes antes
de decidir.

### (b) Resolucion y stride

Con `lite` sobre el video sintetico: bajar de resolucion original (720p) a
480p redujo el tiempo medio por frame de ~23 ms a ~19 ms (stride 1) y subio
el FPS efectivo de ~43 a ~53. Con stride 2 el efecto se compone (hasta ~69
FPS efectivo). El mismo efecto no fue claro en `full`/`heavy`, otra vez
posiblemente por el corto-circuito de "sin persona detectada" descrito
arriba.

**No medido:** el efecto de resolucion/stride sobre la *calidad* de
deteccion (visibilidad, ruido de la serie, si se sigue detectando el salto)
— es la mitad mas importante de esta pregunta y necesita video real. Bajar
resolucion o saltar frames barato en tiempo de CPU, pero puede degradar la
deteccion si la persona queda muy pequena en el frame o si el salto dura
pocos frames y el stride se come informacion del despegue/aterrizaje.

### (c) Concurrencia de workers

Ver "Corrida de concurrencia" abajo: el mecanismo (Dockerfile + limites de
recursos + 2 procesos en paralelo) esta implementado y probado, pero el
resultado numerico obtenido en la laptop de desarrollo no es confiable como
cifra de VPS real (ver la lectura honesta en esa seccion). No se pudo
determinar con confianza cuantos workers concurrentes soporta un CPX21 sin
degradar el tiempo por debajo de un SLA aceptable.

### (d) VPS: CPX21 (3 vCPU/4GB) vs CPX31 (4 vCPU/8GB)

Con los datos de memoria de (a): `heavy` a ~340 MB de RSS por proceso deja
margen en 3-4 GB para varios procesos concurrentes si el resto del sistema
(SO, Postgres/Redis si comparten el VPS, buffers de video) no supera ~2-3 GB.
`lite`/`full` (~250-280 MB) dejan mas margen. Esto es una estimacion de
memoria en reposo con un solo frame en vuelo; no incluye el pico real durante
la decodificacion de video 1080p (que puede ser el cuello de botella real de
memoria, no medido aqui con contenido real).

**Recomendacion preliminar:** CPX21 (3 vCPU/4GB) alcanza para 1-2 analisis
concurrentes con `lite`/`full`; para confirmar cuantos workers concurrentes
soporta sin degradar el tiempo por debajo de un SLA aceptable hace falta la
corrida de concurrencia con video real (ver (c) y "pendientes"). Si el
volumen esperado en el corto plazo es bajo (pocos analisis simultaneos),
CPX21 es razonable para arrancar; CPX31 es la opcion segura si se quiere
margen para picos sin re-litigar la decision.

### (e) Confiabilidad de fases/angulos

**No se pudo medir con datos reales** — no hubo un solo video con una
persona saltando disponible en este entorno.

Lo que si se validó (`test_spike.py`, 9/9 OK):

- `_angle_at_vertex` y `_angle_from_vertical` dan el angulo correcto sobre
  puntos sinteticos con angulo conocido (90°, 180°, 0°, 45°).
- `pick_side` elige el lado de mayor visibilidad.
- `interpolate_gaps` rellena huecos (frames sin deteccion) sin dejar NaN.
- El suavizado (`LandmarkSeriesPreprocessor`) reduce el ruido medido
  (desviacion estandar del delta frame a frame) sobre una señal ruidosa
  sintetica.
- `JumpPhaseDetector` encuentra correctamente despegue/apice/aterrizaje sobre
  una trayectoria de salto sintetica (parabola/gaussiana), y devuelve `None`
  (no jump detected) sobre una serie plana sin salto.

Esto da confianza en que la *logica* es correcta. No dice nada sobre si
`JumpPhaseDetector` va a distinguir bien un salto real (con ruido de
deteccion, oclusiones parciales, camara con leve movimiento) de un
falso positivo/negativo — eso solo se sabe corriendo con saltos grabados de
verdad y revisando visualmente los `series.png` y los frames anotados.

**Pendiente:** correr el spike con 5-10 videos reales de saltos (idealmente
variando iluminacion, ropa, y si la persona sale completa en cuadro) y
reportar sobre esos: % de aciertos de deteccion de fase, comparacion visual
del angulo de aterrizaje reportado contra una medicion manual/goniometro en
al menos un caso, y cuantos casos devuelven `None` (equivalente a
`NO_JUMP_DETECTED`) deberian haber detectado un salto.

### (f) Tamano de video vs limite de 60 MB

**No se pudo medir.** No hubo un video grabado en condiciones reales (celular,
compresion H.264 tipica de una app movil) disponible en este entorno; el
video sintetico usado para el smoke test pesa ~34 MB para 5 s a 720p porque
esta codificado con ruido aleatorio (practicamente incompresible), lo cual no
es representativo de un video real y se descarta a proposito para esta
pregunta.

**Pendiente:** grabar 2-3 saltos con la app/camara de telefono real, en la
resolucion y duracion tipicas esperadas (ver §7 y §2.1 de
`docs/design/video-analysis-pipeline.md`), y registrar tamano en MB y
duracion con este mismo spike (`video_size_mb`/`video_duration_sec`, ya
expuestos en `output/run_summary.md`) para comparar contra el limite de 60 MB.

### Corrida de concurrencia (Docker, 2 vCPU / 3 GB)

Video sintetico, modelo `full`, 720p, stride 1, contenedor `pose-spike` (ver
Dockerfile). Tres escenarios:

| Escenario | t medio/frame (ms) | FPS efectivo | RSS pico (MB) |
|---|---|---|---|
| 1 proceso, `--cpus=2 --memory=3g` | 26.96 | 37.1 | 310 |
| 2 procesos en paralelo, cada uno `--cpus=2` (con margen: host tiene 6 CPUs) | 31.9 / 32.2 | 31.3 / 31.1 | 317 / 321 |
| 2 procesos en paralelo, **pineados a los mismos 2 nucleos fisicos** (`--cpuset-cpus=0,1`, sin `--cpus`) | 25.4 / 26.1 | 39.4 / 38.2 | 315 / 316 |

**Lectura honesta:** el segundo escenario (cada contenedor con su propia
cuota de 2 CPUs en un host de 6) muestra una degradacion leve (~18-19% mas
lento) frente al proceso unico, esperable porque igual compiten por cache/IO
y por otros contenedores del host (Postgres, pgAdmin, etc. tambien estaban
corriendo). El tercer escenario, forzando a ambos procesos a compartir
literalmente los mismos 2 nucleos (la simulacion mas fiel de "2 analisis
simultaneos en un VPS de 2 vCPU"), no mostro degradacion medible frente al
proceso unico — el tiempo por frame incluso fue levemente menor. Esto es
sorprendente y **no deberia tomarse como que la concurrencia es gratis**: la
maquina de desarrollo tiene ruido de fondo (otros 6 contenedores corriendo, VM
de Docker Desktop, filesystem por bind-mount en Windows) que domina la
variacion mas que la contencion de CPU real de 2 procesos livianos de
inferencia. Es un micro-benchmark de baja confianza, no una medicion de VPS.

**Recomendacion:** repetir exactamente este mismo comando (`docker run
--cpuset-cpus=0,1 --memory=3g|4g pose-spike ...`, con 2 y con 3 procesos en
paralelo) directamente en un Hetzner CPX21 real antes de fijar cuantos
workers concurrentes soporta esa VPS. El mecanismo de simulacion (Dockerfile
+ limites de recursos) ya esta listo y probado; falta correrlo en hardware
real y, otra vez, con video real (el contenido sintetico no ejercita la etapa
de landmarks, ver seccion (a)).

### Que no pudo medirse (resumen)

- **Calidad de deteccion real** (% frames sin pose, distribucion de
  visibilidad de rodilla/cadera/tobillo) sobre un salto real.
- **Confiabilidad de `JumpPhaseDetector`** sobre trayectorias reales
  (ruidosas, con oclusiones) — solo validado con datos sinteticos.
- **Precision de los angulos** de rodilla/tronco en aterrizaje contra una
  referencia real (goniometro, video de alta velocidad, etc.).
- **Efecto real de resolucion/stride sobre la calidad** de deteccion (solo
  se midio el efecto sobre el tiempo de CPU).
- **Diferencia real de costo entre lite/full/heavy**: la medicion de este
  spike quedo contaminada por el corto-circuito de "sin persona detectada"
  (ver seccion (a)); no representa el costo con una persona en cuadro.
- **Tamano tipico de un video grabado con la app** vs. el limite de 60 MB.
- **Degradacion real por concurrencia en un VPS de verdad**: se corrio el
  escenario de 2 procesos en paralelo, pero en una laptop de desarrollo con
  otros 6 contenedores activos y filesystem por bind-mount en Windows —
  ruido suficiente para que el numero no sea confiable (ver "Corrida de
  concurrencia"). El mecanismo de medicion si quedo listo para correrse en
  el VPS real.

### Como completar lo pendiente

1. Conseguir 5-10 videos reales de saltos (lateral, condiciones de uso real
   de la app) y ponerlos en `videos/`.
2. Correr `python run_spike.py` con las 3 variantes de modelo.
3. Revisar `output/run_summary.md` (tabla comparativa) y los `series.png` /
   frames anotados de cada video.
4. Reescribir las secciones (a), (b), (e) y (f) de este reporte con los
   numeros reales, y confirmar o corregir las recomendaciones preliminares
   de (c) y (d).
