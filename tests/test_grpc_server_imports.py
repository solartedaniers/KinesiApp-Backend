import os
import subprocess
import sys

# Dependencias que están en requirements.txt pero no en requirements-grpc.txt
_ABSENT_IN_GRPC_IMAGE = ["fastapi", "starlette", "psycopg2", "kinesiapp_ai", "boto3"]


def test_grpc_server_imports_without_the_rest_only_dependencies() -> None:
    # Bloqueo los módulos en un proceso aparte: si el servidor gRPC los importara, su contenedor no arrancaría
    blocked = "; ".join(f"sys.modules[{name!r}] = None" for name in _ABSENT_IN_GRPC_IMAGE)
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; {blocked}; import app.rpc.server"],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
