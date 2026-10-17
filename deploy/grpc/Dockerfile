# syntax=docker/dockerfile:1
# Junto grpcio en localhost y Envoy expuesto en $PORT. Lo construyo desde la raíz del repo porque necesito
# contracts/ y app/: docker build -f deploy/grpc/Dockerfile .

FROM python:3.12-slim AS codegen
WORKDIR /build
COPY requirements-grpc-build.txt .
RUN pip install --no-cache-dir -r requirements-grpc-build.txt
COPY contracts/proto contracts/proto
COPY scripts/generate_grpc.py scripts/
RUN python scripts/generate_grpc.py

FROM envoyproxy/envoy:v1.40.0 AS envoy

FROM python:3.12-slim
WORKDIR /app
COPY --from=envoy /usr/local/bin/envoy /usr/local/bin/envoy
COPY requirements-grpc.txt .
RUN pip install --no-cache-dir -r requirements-grpc.txt
COPY --from=codegen /build/generated ./generated
COPY app app
COPY deploy/grpc/envoy.yaml.template deploy/grpc/entrypoint.sh deploy/grpc/

ENV PYTHONPATH=/app/generated PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["bash", "deploy/grpc/entrypoint.sh"]
