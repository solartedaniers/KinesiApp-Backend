# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Bibliotecas nativas que cargan opencv y el binario de mediapipe aunque no haya pantalla ni GPU
RUN apt-get update && apt-get install -y --no-install-recommends     libgl1 libglib2.0-0 libegl1 libgles2     && rm -rf /var/lib/apt/lists/*

# Capa de dependencias separada del código para aprovechar la cache de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modelo de pose fijado por versión y checksum: cambiarlo exige actualizar POSE_MODEL_VERSION
ADD --checksum=sha256:5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1     https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task     models/pose_landmarker_full.task

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
