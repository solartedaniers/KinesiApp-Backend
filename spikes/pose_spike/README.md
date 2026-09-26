# Spike: rendimiento de MediaPipe Pose (Fase 0.5)

Spike desechable para medir si MediaPipe Tasks (`PoseLandmarker`) en CPU es
viable para el pipeline de analisis de saltos descrito en
`docs/design/video-analysis-pipeline.md`, antes de comprometer esa fase.

**No es parte del backend.** No toca `app/`, tests ni `requirements.txt` del
proyecto. Tiene su propio entorno y dependencias (`requirements-spike.txt`).

## 1. Instalar

```bash
cd backend/spikes/pose_spike
python -m venv .venv-spike
source .venv-spike/bin/activate   # Windows: .venv-spike\Scripts\activate
pip install -r requirements-spike.txt
```

Probado con Python 3.11-3.12 (target del Dockerfile) y, de forma exploratoria,
tambien corre en Python 3.14 en este equipo. Para reproducibilidad con el VPS
de destino (Linux) se recomienda 3.11-3.12.

## 2. Descargar los modelos

Los `.task` van en `models/` (ignorado por git). Descargar las 3 variantes:

```bash
mkdir -p models
curl -L -o models/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task
curl -L -o models/pose_landmarker_full.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task
curl -L -o models/pose_landmarker_heavy.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task
```

Tamanos aproximados: lite ~5.5 MB, full ~9 MB, heavy ~29 MB. Referencia:
https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker

## 3. Poner videos de prueba

Videos en `videos/` (ignorado por git), formatos `.mp4/.mov/.avi/.mkv`.
Idealmente: saltos grabados en vista lateral, en las condiciones reales que
usara la app (telefono en mano, mismo tipo de resolucion/duracion esperado en
produccion), para que la medicion de calidad de deteccion sea representativa.

**Importante (ver REPORT.md):** en este entorno no hubo videos reales de
saltos disponibles para correr el spike de punta a punta. Los modulos de
logica (angulos, suavizado, deteccion de fases) tienen un auto-chequeo con
datos sinteticos (`test_spike.py`), y el pipeline completo se probo de
extremo a extremo con un video sintetico sin persona real (solo valida que el
codigo corre, no la calidad de deteccion). Para obtener las metricas reales
que pide este spike hace falta correrlo con grabaciones reales.

## 4. Correr

```bash
python run_spike.py \
  --videos-dir videos --models-dir models --output-dir output \
  --model-variants lite,full,heavy \
  --resolutions original,720,480 \
  --strides 1,2,3
```

Todos los valores tienen default documentado en `--help`; nada esta
hardcodeado en el codigo. Salidas por combinacion video x modelo x resolucion
x stride, en `output/<video>/<modelo>/res-<res>_stride-<n>/`:

- `series.png`: angulos de rodilla/tronco por frame, con despegue/apice/aterrizaje marcados (si se detecto salto).
- `despegue_frameN.png`, `apice_frameN.png`, `aterrizaje_frameN.png`, `mid_ascenso_*.png`, `mid_descenso_*.png`: frames anotados con el esqueleto.

Y `output/run_summary.md`: una tabla con los datos crudos de todas las
combinaciones (tiempos, RSS, calidad de deteccion, angulos en aterrizaje).
Esa tabla es la base de datos para escribir `REPORT.md`; no reemplaza el
analisis.

### Auto-chequeo de la logica (sin video real)

```bash
python test_spike.py
```

Valida angulos, interpolacion/suavizado y deteccion de fases con datos
sinteticos controlados (no depende de mediapipe ni de un video).

## 5. Simulacion de VPS (2 vCPU / 3-4 GB)

```bash
docker build -t pose-spike .
docker run --rm --cpus="2" --memory="3g" \
  -v "$(pwd)/videos:/spike/videos" \
  -v "$(pwd)/models:/spike/models" \
  -v "$(pwd)/output:/spike/output" \
  pose-spike --model-variants lite,full --resolutions 720 --strides 1
```

Para medir degradacion bajo carga concurrente (2 procesos en paralelo,
simulando 2 analisis simultaneos en el VPS), correr dos contenedores a la vez
compitiendo por el mismo limite de CPU/memoria:

```bash
docker run --rm --cpus="2" --memory="3g" -v "$(pwd)/videos:/spike/videos" \
  -v "$(pwd)/models:/spike/models" -v "$(pwd)/output:/spike/output_a" \
  pose-spike --model-variants full --resolutions 720 --strides 1 &
docker run --rm --cpus="2" --memory="3g" -v "$(pwd)/videos:/spike/videos" \
  -v "$(pwd)/models:/spike/models" -v "$(pwd)/output:/spike/output_b" \
  pose-spike --model-variants full --resolutions 720 --strides 1 &
wait
```

Comparar `t_medio_ms`/`fps_efectivo` de `output_a` y `output_b` contra una
corrida sin competencia (1 solo proceso) para ver el impacto real.

## 6. Nota sobre limite de hilos

La Tasks API de mediapipe (`PoseLandmarkerOptions`/`BaseOptions`, version
instalada aqui) no expone un parametro de numero de hilos para el delegado
CPU. `--num-threads` setea `OMP_NUM_THREADS`/`TFLITE_NUM_THREADS`/
`OPENBLAS_NUM_THREADS` antes de importar mediapipe (mejor esfuerzo). El
limite confiable es el de `docker run --cpus`, que ademas es el que replica
de verdad las condiciones del VPS.

## Estructura

```
pose_spike/
  run_spike.py          CLI
  test_spike.py         auto-chequeo de logica pura
  requirements-spike.txt
  Dockerfile
  REPORT.md             hallazgos y recomendaciones
  spike/
    video_source.py     lectura de video, resize, stride
    landmarker.py        wrapper de PoseLandmarker (VIDEO e IMAGE mode)
    timing.py            tiempos por frame, RSS pico
    angles.py             flexion de rodilla/tronco desde landmarks
    smoothing.py           interpolacion de huecos + media movil + ruido
    phases.py               deteccion de despegue/apice/aterrizaje
    quality.py                % frames sin pose, visibilidad
    annotate.py                dibujo del esqueleto sobre un frame
    plotting.py                  graficos de series con fases marcadas
    pipeline.py                   orquesta todo lo anterior
    report.py                      tabla markdown de resultados crudos
  videos/, models/, output/    ignorados por git (ver .gitignore)
```
