# KinesiApp Backend

Es el servidor de KinesiApp: un servidor gRPC asíncrono en Python (`grpcio` asyncio) sobre Postgres de Neon. Atiende cuentas, sesiones, deportistas, equipos, análisis de movimiento y el chat. El análisis de video y el modelo de lenguaje no corren aquí: se los pido al microservicio de IA por gRPC.

No hay API REST. Todo lo que entra y sale son RPC definidos en [KinesiApp-Contracts](https://github.com/solartedaniers/KinesiApp-Contracts).

## Arquitectura

```
Next.js (Vercel fra1) ──gRPC-Web, HTTP/1.1──▶ Envoy :$PORT ──gRPC nativo──▶ grpcio :50051
                                                 (mismo contenedor, Render Frankfurt)
                                                                    │
                                    asyncpg ◀────────────┤────────────▶ IA: gRPC nativo + TLS
                                 Neon Postgres (Frankfurt) │              (Azure Container Apps)
                                                           ▼
                                             Neon Storage (S3, buckets privados)
```

- **Contract-first.** Traigo los contratos como submódulo en `contracts/`, fijado a un tag (hoy `v0.9.0`). `scripts/generate_grpc.py` genera el código Python en `generated/`, que no se versiona. Nunca implemento un RPC que no esté en el contrato.
- **Envoy delante de grpcio.** Render solo acepta HTTP/1.1 desde internet, así que en el mismo contenedor Envoy recibe gRPC-Web en `$PORT`, lo traduce a gRPC nativo hacia `grpcio` en localhost y responde `/healthz`. Solo reenvía rutas `/kinesiapp.*` (`deploy/grpc/`).
- **Servicios** (`app/rpc/*_servicer.py`): `SystemService`, `AuthService`, `AccountService`, `UserAdminService`, `AthleteProfileService`, `ManagedAthleteService`, `TeamService`, `AnalysisService` y `ChatService`. `AccountService` es lo que la persona hace sobre su propia cuenta, y `UserAdminService` lo que hace un admin sobre las demás. Por eso son servicios distintos.
- **Interceptores.** Toda llamada pasa por tres:
  - registro (método, status y duración);
  - errores: un `DomainError` se convierte en el status estándar de gRPC con `google.rpc.ErrorInfo` (`reason` en UPPER_SNAKE_CASE, dominio `kinesiapp`) y, si aplica, `BadRequest` con el campo que falló;
  - autenticación: lee la opción `(kinesiapp.common.v1.access)` de cada RPC y verifica el `authorization: Bearer <token>` de la metadata.

  El mapeo de errores está centralizado en `app/rpc/error_status.py`, sin strings sueltos.
- **Capas.** Cada servicer valida la entrada con Pydantic (`inputs.py` de cada dominio) y delega en un caso de uso de su dominio (`app/auth`, `app/account`, `app/admin`, `app/athletes`, `app/teams`, `app/analysis`, `app/chat`). Los casos de uso usan repositorios asíncronos dentro de un `UnitOfWork` (una sesión y una transacción por caso de uso). `app/rpc/service_factory.py` arma todo y es el único lugar que conoce las implementaciones concretas.
- **Patrones que uso**, cada uno para resolver un problema concreto:
  - *Repository* y *Unit of Work* para la base;
  - *Adapter* para la IA, el almacenamiento y el correo;
  - *Factory* para los transportes de la IA y el almacenamiento firmado;
  - *Strategy* para el transporte de la IA (gRPC nativo o gRPC-Web);
  - *Decorator* para despertar la IA y reintentar (`WarmingMovementAnalyzer`, `ResilientAssistant`);
  - *Observer* para el progreso del análisis (`AnalysisProgressHub`).

## Flujos principales

- **Video.**
  1. `CreateVideoUpload` comprueba el consentimiento y los límites, y devuelve una URL firmada de subida al bucket privado más un `upload_id`.
  2. El navegador sube directo a Neon Storage.
  3. `ConfirmVideoUpload` revisa lo que llegó y encola el análisis.
  4. `WatchAnalysis` es server streaming: emite el progreso por etapas hasta el resultado.
  5. `GetVideoPlaybackUrl` da una URL firmada de lectura de vida corta.
- **Análisis.**
  - `AnalysisRunner` procesa en segundo plano con un tope de concurrencia.
  - Antes de cada intento despierto la IA con `WarmUp`. El ingress de Azure corta el stream que despierta la réplica, así que reintento con espera exponencial ante `INTERNAL` o `UNAVAILABLE`.
  - Cada intento reclama el análisis con un `UPDATE` atómico y un lease que renueva al guardar progreso, para que dos instancias no lo procesen a la vez durante un deploy.
  - Al arrancar, recupero los análisis que quedaron a medias.
- **Chat.** No armo el prompt aquí. Le mando a la IA los datos estructurados del análisis y el historial, guardo cada mensaje y reenvío la respuesta en streaming. Limito las preguntas por hilo por hora y las de todos por minuto, para cuidar la cuota de Gemini.
- **Estado de la IA.** `WakeUpAi` despierta la IA y espera a que esté lista. Si no responde, devuelvo `UNAVAILABLE` y el frontend lo muestra sin romperse.
- **Política del cliente.** `GetClientPolicy` publica los límites que el frontend valida antes de enviar. Son la versión del consentimiento, la duración y el tamaño del video, la contraseña, la edad, la estatura, el peso y el largo del chat. Todos salen de la configuración, y el backend los vuelve a validar.

## Configuración

Toda la configuración está en `app/settings/`, como clases de `pydantic-settings` por dominio. Cada servicio recibe solo la suya. `.env.example` lista cada variable:

- las que no tienen valor son obligatorias;
- las comentadas tienen un default.

Los secretos (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `AI_SERVICE_TOKEN`...) no tienen default: si falta uno, el servidor no arranca.

## Cómo correrlo

Necesito Python 3.12 y una base de Neon (no hay Postgres local).

```bash
git clone --recurse-submodules https://github.com/solartedaniers/KinesiApp-Backend.git
cd KinesiApp-Backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # en Linux/macOS: .venv/bin/pip
python scripts/generate_grpc.py      # genera generated/ desde contracts/
cp .env.example .env                 # y lleno los valores
```

1. **Migrar.** Las migraciones las corro desde local contra el endpoint directo de Neon (sin `-pooler`), nunca desde el contenedor:
   ```bash
   alembic upgrade head
   alembic check                      # confirma que no hay drift entre modelos y migraciones
   ```
2. **Crear el primer admin.** Es idempotente: si el correo ya existe, solo lo promueve. La contraseña se pide por consola o llega por `ADMIN_PASSWORD` y nunca se imprime.
   ```bash
   python -m app.cli create-admin
   ```
3. **Levantar el servidor solo** (en `GRPC_HOST:GRPC_PORT`, por defecto `127.0.0.1:50051`):
   ```bash
   PYTHONPATH=generated python -m app.rpc.server
   ```
4. **O el contenedor completo con Envoy**, como en Render:
   ```bash
   docker build -f deploy/grpc/Dockerfile -t kinesiapp-grpc .
   docker run --rm --env-file .env -e PORT=10000 -p 10000:10000 kinesiapp-grpc
   ```
   El frontend local apunta a él con `GRPC_WEB_BASE_URL=http://localhost:10000`. Para probarlo a mano sirve `buf curl --protocol grpcweb`.

## Pruebas

```bash
pytest                              # pytest.ini agrega generated/ al path
```

- Las pruebas nunca tocan Neon, Resend, la IA ni el bucket real. Corren sobre SQLite asíncrono (`aiosqlite`), y `tests/conftest.py` pone variables ficticias que le ganan al `.env`.
- Las pruebas de RPC levantan un servidor gRPC real en un puerto libre, con los interceptores de verdad (`tests/grpc_harness.py`, `tests/rpc_world.py`). La IA y el bucket son dobles en memoria.
- `tests/test_grpc_server_imports.py` comprueba que el servidor arranca sin FastAPI, sin la IA como librería y sin Alembic. Esas dependencias no van en la imagen.
- `scripts/cloud_check.py` es la prueba de punta a punta contra el despliegue real. Usa `buf curl` por gRPC-Web, con cuentas de prueba, y borra todo lo que crea.

## Despliegue

- **Render (Frankfurt), junto a Neon.** Es un servicio Docker con `deploy/grpc/Dockerfile`, que hace tres cosas:
  1. genera el código de los contratos en una etapa aparte;
  2. copia el binario de Envoy;
  3. instala solo `requirements.txt`.

  `deploy/grpc/entrypoint.sh` arma la configuración de Envoy con el `$PORT` que asigna Render, levanta los dos procesos y termina el contenedor si cualquiera cae.
- Las variables se definen en Render. La IA se alcanza con `AI_TRANSPORT=grpc`, `AI_GRPC_TLS=true` y `AI_SERVICE_URL=<fqdn de Container Apps>:443`.
- Antes de desplegar un cambio de esquema, corro `alembic upgrade head` desde local.
- Mover el backend de Oregón a Frankfurt bajó las llamadas simples de 2.5–4 s a ~0.6 s. Cada RPC autenticado hace unas 20 idas y vueltas a la base, y la distancia a Neon las multiplicaba.
