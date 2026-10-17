#!/usr/bin/env bash
set -euo pipefail

# Render asigna el puerto público en PORT
LISTEN_PORT="${PORT:-8080}"
GRPC_PORT="${GRPC_PORT:-50051}"
export GRPC_PORT

sed -e "s/__LISTEN_PORT__/${LISTEN_PORT}/" -e "s/__GRPC_PORT__/${GRPC_PORT}/" \
  deploy/grpc/envoy.yaml.template > /tmp/envoy.yaml

python -m app.rpc.server &
envoy -c /tmp/envoy.yaml --log-level warn &

# Reenvío SIGTERM a los dos procesos para que grpcio cierre ordenado cuando Render detiene el contenedor
trap 'kill -TERM $(jobs -p) 2>/dev/null || true' TERM INT

# Si cualquiera de los dos cae, termino el contenedor para que Render lo reinicie en vez de dejar
# a Envoy respondiendo sin backend
set +e
wait -n
status=$?
kill -TERM $(jobs -p) 2>/dev/null
wait
exit "$status"
