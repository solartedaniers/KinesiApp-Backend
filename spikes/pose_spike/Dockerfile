# Imagen para simular el VPS objetivo (Hetzner CPX21: 3 vCPU / 4GB) al correr el spike.
# No es la imagen de produccion del backend: es solo para medir bajo limites de recursos.
FROM python:3.11-slim

WORKDIR /spike

# libgl1/libglib para opencv-python-headless; libegl1/libgles2 porque el
# binario nativo de mediapipe los carga en tiempo de ejecucion aunque no haya GPU
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-spike.txt .
RUN pip install --no-cache-dir -r requirements-spike.txt

COPY . .

ENTRYPOINT ["python", "run_spike.py"]
