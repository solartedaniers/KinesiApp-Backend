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

- **Contract-first.** Traigo los contratos como submódulo en `contracts/`, fijado a un tag (hoy `v0.11.0`). `scripts/generate_grpc.py` genera el código Python en `generated/`, que no se versiona. Nunca implemento un RPC que no esté en el contrato.
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

## Requisitos

- **Python 3.12**, la misma versión de la imagen (`python:3.12-slim`).
- **Git** con submódulos, porque los contratos llegan en `contracts/`.
- **Docker** (uso Docker Desktop 29.4), solo si quiero correr el contenedor con Envoy como en Render.
- **buf 1.74**, solo para `scripts/cloud_check.py` y para probar RPC a mano con `buf curl`. Si no está en el PATH, el script usa el que instala el frontend en `../KinesiApp-Frontend/node_modules/.bin`.
- **Una branch de Neon y un bucket de Neon Storage** para desarrollo. No hay Postgres local.

## Configuración

Toda la configuración está en `app/settings/`, como clases de `pydantic-settings` por dominio. Cada servicio recibe solo la suya. En `.env.example`, las variables sin valor son obligatorias y las comentadas tienen un default. Los secretos no tienen default: si falta uno, el servidor no arranca.

Copio `.env.example` a `.env` y lo lleno así. Ningún valor real va al repo: el `.env` está en `.gitignore`.

**Base de datos**

| Variable | Para qué la uso | De dónde saco el valor | Secreta |
|---|---|---|---|
| `POSTGRES_HOST` | El servidor de mi base en Neon. Para el backend uso el endpoint con `-pooler`; para Alembic, el directo, sin `-pooler`. | Neon → mi branch → Connect (con o sin "Connection pooling") | No es secreta, pero no la publico |
| `POSTGRES_USER` | El rol con el que me conecto. | Neon → Connect | No es secreta, pero no la publico |
| `POSTGRES_PASSWORD` | La contraseña de ese rol. | Neon → Connect | **Sí** |
| `POSTGRES_DB` | El nombre de la base dentro de la branch. | Neon → Connect | No |
| `POSTGRES_PORT`, `POSTGRES_SSL_MODE` | 5432 y `require`. Con Neon nunca los cambio. | Default | No |

**Sesión y cuentas**

| Variable | Para qué la uso | De dónde saco el valor | Secreta |
|---|---|---|---|
| `JWT_SECRET_KEY` | Firmo los access y refresh tokens. Si la cambio, se cierran todas las sesiones. | La genero con `python -c "import secrets; print(secrets.token_urlsafe(64))"`, una distinta por ambiente | **Sí** |
| `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | El algoritmo (HS256) y la vida de los tokens: 15 minutos el access y 7 días el refresh. | Default | No |
| `OTP_EXPIRE_MINUTES` | Cuánto vale el código que mando por correo para verificar la cuenta o recuperar la contraseña. | Lo decido yo; uso 10 | No |
| `OTP_LENGTH`, `OTP_MAX_ATTEMPTS` | Dígitos del código (6) e intentos antes de invalidarlo (5). | Default | No |
| `PASSWORD_MIN_LENGTH`, `PASSWORD_MAX_LENGTH` | Las reglas de la contraseña. También las publico en `GetClientPolicy` para que el frontend valide lo mismo. | Default (8 y 128) | No |

**Servidor y contenedor**

| Variable | Para qué la uso | De dónde saco el valor | Secreta |
|---|---|---|---|
| `GRPC_HOST`, `GRPC_PORT` | Dónde escucha `grpcio`. En el contenedor solo lo alcanza Envoy, por localhost. | Default (`127.0.0.1:50051`) | No |
| `GRPC_SHUTDOWN_GRACE_SECONDS` | Cuánto dejo terminar las llamadas en curso al apagar, por ejemplo en un deploy. | Default | No |
| `ENVOY_CONNECT_TIMEOUT` | Solo la lee `deploy/grpc/entrypoint.sh`: lo que espera Envoy para conectar con `grpcio`. | Default (`1s`) | No |
| `PORT` | El puerto público de Envoy. No va en el `.env`. | Render lo asigna solo; en local paso `-e PORT=10000` | No |

**Correo (Resend)**

| Variable | Para qué la uso | De dónde saco el valor | Secreta |
|---|---|---|---|
| `RESEND_API_KEY` | Mando los códigos de verificación y de recuperación de contraseña. Sin ella, enviar falla con `EMAIL_DELIVERY_FAILED`. | Resend → API Keys | **Sí** |
| `RESEND_FROM_EMAIL` | El remitente, que acepta el formato `Nombre <correo>`. Tiene que ser de un dominio verificado en Resend; con `onboarding@resend.dev`, Resend solo entrega al dueño de la cuenta. | Lo defino yo | No |
| `RESEND_TIMEOUT_SECONDS` | El plazo de cada envío. | Default (15) | No |
| `EMAIL_DNS_TIMEOUT_SECONDS` | Al registrar a alguien, reviso que el dominio de su correo tenga MX. Este es el plazo de esa consulta. | Default (5) | No |

**Archivos (Neon Storage)**

| Variable | Para qué la uso | De dónde saco el valor | Secreta |
|---|---|---|---|
| `AWS_ENDPOINT_URL_S3`, `AWS_REGION` | El endpoint compatible con S3 de Neon Storage y su región. Uso los nombres de boto3. | Neon → Storage | No es secreta, pero no la publico |
| `AWS_ACCESS_KEY_ID` | Con ella firmo las URLs de subida y de lectura. | Neon → Storage → claves de acceso | **Sí** |
| `AWS_SECRET_ACCESS_KEY` | La parte secreta de esa clave. | Neon → Storage → claves de acceso | **Sí** |
| `S3_PRIVATE_IMAGES_BUCKET`, `S3_PRIVATE_VIDEOS_BUCKET` | Los buckets privados de avatares y de videos. Sin ellos, subir o leer responde `STORAGE_UNAVAILABLE`. | Los creo en Neon Storage: `kinesiapp-dev-*` para desarrollo y `kinesiapp-prod-*` para producción | No |
| `S3_IMAGES_BUCKET` | Solo la usa la migración vieja `151f2ecce8b2`, que pasó los avatares de la base a un bucket. El servidor no la lee. | Default (`images`) | No |

**Límites de negocio** (todos con default; los que ve la persona salen también por `GetClientPolicy`)

| Variable | Para qué la uso |
|---|---|
| `MAX_VIDEO_UPLOAD_BYTES`, `MAX_VIDEO_DURATION_SECONDS`, `MAX_AVATAR_UPLOAD_BYTES` | Topes del video (100 MB y 40 s) y del avatar (1 MB). |
| `VIDEO_CONSENT_VERSION` | La versión vigente del consentimiento de video. Si la subo, cada persona tiene que aceptar de nuevo antes de subir. |
| `SIGNED_UPLOAD_URL_EXPIRE_SECONDS`, `UPLOAD_TICKET_EXPIRE_SECONDS`, `SIGNED_READ_URL_EXPIRE_SECONDS` | La vida de la URL de subida (15 min), del `upload_id` (1 h) y de la URL de lectura (5 min). |
| `PAGE_SIZE_DEFAULT`, `PAGE_SIZE_MAX` | El tamaño de página de los listados. |
| `ATHLETE_MIN_AGE_YEARS` … `ATHLETE_MAX_WEIGHT_KG` | Los rangos de edad, estatura y peso de la ficha. Fuera de ellos, casi siempre es una unidad equivocada. |
| `CHAT_MESSAGE_MAX_CHARS`, `CHAT_RATE_LIMIT_PER_USER_PER_HOUR`, `CHAT_RATE_LIMIT_GLOBAL_PER_MINUTE` | El largo de cada pregunta y los límites que cuidan la cuota de Gemini. |
| `RISK_LEVEL_MODERATE`, `RISK_LEVEL_HIGH` | Los cortes del puntaje de la IA para "moderado" y "alto". |

**IA**

| Variable | Para qué la uso | De dónde saco el valor | Secreta |
|---|---|---|---|
| `AI_SERVICE_URL` | Dónde está la IA. Con `grpc` es `host:443`; con `grpc-web`, la URL de su Envoy (`http://localhost:8080` en local). | Azure → `kinesiapp-ia` → Application Url, sin `https://` y con `:443` | No |
| `AI_SERVICE_TOKEN` | El secreto compartido con la IA, de 32 caracteres o más. Tiene que ser idéntico al `AI_SERVICE_TOKEN` de la IA. | Lo genero con `secrets.token_urlsafe(48)` | **Sí** |
| `AI_TRANSPORT`, `AI_GRPC_TLS` | `grpc` con TLS en producción, porque el ingress de Azure acepta HTTP/2. En local, `grpc-web` contra el contenedor de la IA. | Lo decido yo | No |
| `AI_CONNECT_TIMEOUT_SECONDS`, `AI_WAKE_UP_TIMEOUT_SECONDS`, `AI_WAKE_UP_RETRY_INTERVAL_SECONDS`, `AI_WAKE_UP_CALL_TIMEOUT_SECONDS` | Plazos para conectar y despertar la IA. Espero 60 s porque medí 33 s desde dormida. | Default | No |
| `AI_ASSISTANT_TIMEOUT_SECONDS`, `AI_ASSISTANT_ATTEMPTS` | El plazo de una respuesta del chat y los intentos si la conexión se corta antes del primer texto. | Default | No |
| `ANALYSIS_STREAM_TIMEOUT_SECONDS`, `ANALYSIS_MAX_ATTEMPTS`, `ANALYSIS_RETRY_*` | 180 s por intento (bajo los 240 s del ingress de Azure), 4 intentos y una espera que se duplica hasta 60 s. | Default | No |
| `ANALYSIS_MAX_CONCURRENCY`, `ANALYSIS_PROGRESS_PERSIST_INTERVAL_SECONDS` | Cuántos análisis corro a la vez y cada cuánto guardo el progreso. | Default | No |
| `ANALYSIS_PROCESSING_LEASE_SECONDS`, `ANALYSIS_RECOVERY_INTERVAL_SECONDS` | Cuánto dura el reclamo de un análisis y cada cuánto busco los que quedaron a medias. El lease tiene que superar el despertar más un intento, o el backend no arranca. | Default | No |

**Fuera del `.env`.** `python -m app.cli create-admin` lee `ADMIN_EMAIL`, `ADMIN_PASSWORD` (secreta) y `ADMIN_FULL_NAME` si existen. Si no, me las pide en la terminal.

## Cómo correrlo

```bash
git clone --recurse-submodules https://github.com/solartedaniers/KinesiApp-Backend.git
cd KinesiApp-Backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # en Linux/macOS: .venv/bin/pip
python scripts/generate_grpc.py      # genera generated/ desde contracts/
cp .env.example .env                 # y lo lleno con la tabla de Configuración
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

## Errores comunes

| Lo que veo | Por qué pasa | Cómo lo arreglo |
|---|---|---|
| `contracts/` está vacío o `generate_grpc.py` no encuentra los `.proto` | Cloné sin `--recurse-submodules`. | `git submodule update --init` y vuelvo a generar. |
| `ModuleNotFoundError: No module named 'kinesiapp'` | No generé el código o `generated/` no está en el path. | `python scripts/generate_grpc.py`. Al levantar el servidor, `PYTHONPATH=generated` (en PowerShell, `$env:PYTHONPATH="generated"`). |
| El servidor no arranca con un `ValidationError` de pydantic | Falta una variable obligatoria o tiene un valor inválido, por ejemplo un `AI_SERVICE_TOKEN` de menos de 32 caracteres. | El error dice el nombre de la variable; la busco en la tabla de Configuración. |
| No arranca porque el lease es muy corto | `ANALYSIS_PROCESSING_LEASE_SECONDS` no supera `AI_WAKE_UP_TIMEOUT_SECONDS` + `ANALYSIS_STREAM_TIMEOUT_SECONDS`. | Subo el lease o bajo los otros dos. |
| Una migración falla o se comporta raro | La corrí por el endpoint `-pooler`. El pooler de Neon reparte conexiones por transacción y no es para migraciones. | Para migrar, cambio `POSTGRES_HOST` al endpoint directo, sin `-pooler`. |
| La primera llamada tarda varios segundos | Neon suspende la base sin uso y tarda en despertar. | Es normal. `pool_pre_ping` reemplaza la conexión cerrada y la siguiente ya va rápida. |
| `EMAIL_DELIVERY_FAILED` | Falta `RESEND_API_KEY`, o el remitente no es de un dominio verificado. Con `onboarding@resend.dev`, Resend solo entrega al dueño de la cuenta. | Pongo la clave y un remitente de un dominio verificado. |
| `STORAGE_UNAVAILABLE` al subir o leer un archivo | Faltan las credenciales de Neon Storage o los buckets privados. | Lleno `AWS_*` y `S3_PRIVATE_*`. |
| El navegador bloquea la subida al bucket por CORS | El origen del frontend no está en el CORS del bucket. | Agrego el origen al CORS del bucket (en desarrollo, `http://localhost:3000`) y lo compruebo con `scripts/cloud_check.py`, que hace el preflight desde cada origen. |
| `UNAVAILABLE` con reason `AI_UNAVAILABLE` | La IA está dormida (escala a cero) o `AI_SERVICE_URL` está mal. | En frío tarda 20–33 s en despertar y el backend reintenta solo. Si sigue, reviso la URL y que la revisión de Azure esté sana. |
| `UNAUTHENTICATED` desde la IA | El `AI_SERVICE_TOKEN` del backend no es el mismo que el de la IA. | Pongo el mismo valor en Render y en los secretos de Container Apps. |

## Flujo de trabajo

- **Trabajo en ramas feature.** Aquí es `feature/grpc-backend`. Nunca hago commit directo en `main`; fusiono con `--no-ff` cuando el cambio está probado.
- **El push a `main` despliega a producción.** Render reconstruye el backend desde `main` y Vercel hace lo mismo con el frontend. Las ramas feature del backend no se despliegan.
- **La IA necesita un paso a mano.** Su push construye la imagen `ghcr.io/solartedaniers/kinesiapp-ai:<sha>`, pero Azure sigue en la revisión anterior hasta que corro `az containerapp update -n kinesiapp-ia -g kinesiapp-rg --image ghcr.io/solartedaniers/kinesiapp-ai:<sha>`.
- **Las migraciones se corren a mano.** El contenedor no migra al arrancar. Antes de fusionar un cambio de esquema, corro `alembic upgrade head` desde local contra production, por el endpoint directo.
- **Las previews usan la base real.** Cada rama del frontend tiene un preview en Vercel que habla con este backend de producción, así que lo que creo en un preview queda en la base de production. Para probar con datos de mentira uso el entorno local contra grpc-dev.
- **Contract-first.** Si cambia un RPC, primero va el contrato con un tag nuevo en KinesiApp-Contracts. Después muevo el submódulo y regenero.

## Producción

La app está publicada en **https://www.kinesiapp.com**.

| Servicio | Dónde corre | Cómo llega a producción |
|---|---|---|
| Frontend (Next.js) | Vercel, con las funciones en `fra1` (Fráncfort) | Push a `main`, automático |
| Backend (Envoy + `grpcio`) | Render en Frankfurt, como servicio Docker: https://kinesiapp-backend-grpc.onrender.com | Push a `main`, automático |
| IA (Envoy + `grpcio`) | Azure Container Apps en `canadacentral`, con 0 a 1 réplica | `az containerapp update` con la imagen de GHCR |
| Base de datos | Neon Postgres en Frankfurt, branch `production` | Migraciones a mano con Alembic |
| Archivos | Neon Storage, buckets privados `kinesiapp-prod-images` y `kinesiapp-prod-videos` | — |
| Correo | Resend | — |
| Dominio | `kinesiapp.com`, comprado en Namecheap, con DNS hacia Vercel | — |

- **Correos.** Los códigos de verificación y de recuperación de contraseña salen desde `KinesiApp <no-reply@kinesiapp.com>` con Resend. El dominio `kinesiapp.com` está verificado en Resend, así que los correos llegan a cualquier persona y no solo al dueño de la cuenta.
- **CORS de los buckets.** Los de producción solo aceptan `https://www.kinesiapp.com`, `https://kinesiapp.com` y las previews de Vercel (`https://kinesiapp-*-solartedaniers-projects.vercel.app`). Además, solo permiten PUT, GET y HEAD. Cualquier otro origen recibe el preflight rechazado.

## Despliegue

- **Render (Frankfurt), junto a Neon.** Es un servicio Docker con `deploy/grpc/Dockerfile`, que hace tres cosas:
  1. genera el código de los contratos en una etapa aparte;
  2. copia el binario de Envoy;
  3. instala solo `requirements.txt`.

  `deploy/grpc/entrypoint.sh` arma la configuración de Envoy con el `$PORT` que asigna Render, levanta los dos procesos y termina el contenedor si cualquiera cae.
- Las variables se definen en Render. La IA se alcanza con `AI_TRANSPORT=grpc`, `AI_GRPC_TLS=true` y `AI_SERVICE_URL=<fqdn de Container Apps>:443`.
- Antes de desplegar un cambio de esquema, corro `alembic upgrade head` desde local, por el endpoint directo de Neon (no el `-pooler`).

### Ambientes

| | Producción | Desarrollo |
|---|---|---|
| Servicio | `kinesiapp-backend-grpc` en Render, desde `main`: https://kinesiapp-backend-grpc.onrender.com | el servidor (`python -m app.rpc.server`) o el contenedor, en local |
| Base | branch `production` de Neon (`-pooler`), Alembic en la head `a2d6f8c4e157` | branch `grpc-dev` |
| Archivos | `kinesiapp-prod-images` y `kinesiapp-prod-videos`, privados, con CORS solo para `kinesiapp.com`, `www.kinesiapp.com` y los previews de Vercel | `kinesiapp-dev-images` y `kinesiapp-dev-videos` |
| Quién lo usa | `www.kinesiapp.com` y también los previews de Vercel | el frontend en local |

- Para volver Render a grpc-dev se cambian cuatro variables (`POSTGRES_HOST`, `S3_PRIVATE_IMAGES_BUCKET`, `S3_PRIVATE_VIDEOS_BUCKET` y `JWT_SECRET_KEY`) y la rama. La URL no cambia.
- `scripts/cloud_check.py` espera por defecto los buckets y orígenes de producción; contra grpc-dev se pasan con `--images-bucket`, `--videos-bucket` y `--origin`.
- `scripts/copy_dev_accounts.py` copió al corte las cuentas elegidas de grpc-dev a producción, con su hash de contraseña, sus datos y sus archivos. Corre en seco por defecto y es idempotente.
- Mover el backend de Oregón a Frankfurt bajó las llamadas simples de 2.5–4 s a ~0.6 s. Cada RPC autenticado hace unas 20 idas y vueltas a la base, y la distancia a Neon las multiplicaba.
