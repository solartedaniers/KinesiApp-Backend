# REPORT — Spike de MediaPipe Pose (Fase 0.5)

## Resumen

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

## Que se hizo

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

## Entorno de medicion

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

## (a) Variante de modelo — lite / full / heavy

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

## (b) Resolucion y stride

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

## (c) Concurrencia de workers

Ver "Corrida de concurrencia" abajo: el mecanismo (Dockerfile + limites de
recursos + 2 procesos en paralelo) esta implementado y probado, pero el
resultado numerico obtenido en la laptop de desarrollo no es confiable como
cifra de VPS real (ver la lectura honesta en esa seccion). No se pudo
determinar con confianza cuantos workers concurrentes soporta un CPX21 sin
degradar el tiempo por debajo de un SLA aceptable.

## (d) VPS: CPX21 (3 vCPU/4GB) vs CPX31 (4 vCPU/8GB)

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

## (e) Confiabilidad de fases/angulos

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

## (f) Tamano de video vs limite de 60 MB

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

## Corrida de concurrencia (Docker, 2 vCPU / 3 GB)

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

## Que no pudo medirse (resumen)

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

## Como completar lo pendiente

1. Conseguir 5-10 videos reales de saltos (lateral, condiciones de uso real
   de la app) y ponerlos en `videos/`.
2. Correr `python run_spike.py` con las 3 variantes de modelo.
3. Revisar `output/run_summary.md` (tabla comparativa) y los `series.png` /
   frames anotados de cada video.
4. Reescribir las secciones (a), (b), (e) y (f) de este reporte con los
   numeros reales, y confirmar o corregir las recomendaciones preliminares
   de (c) y (d).
