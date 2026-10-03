from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import athletes, auth, chat, jump_analyses, managed_athletes, public, users
from app.core.config import settings
from app.core.exceptions import AppException, app_exception_handler

# El esquema lo crea Alembic (alembic upgrade head), no la app al arrancar.
# Ver backend/README.md para el orden de arranque.
app = FastAPI(title=settings.PROJECT_NAME)

app.add_exception_handler(AppException, app_exception_handler)

# add_middleware (no envolver `app` a mano) para que siga siendo la instancia de
# FastAPI: TestClient y `app.dependency_overrides` la necesitan así. El CORS
# igual queda en la pila ASGI completa, así que también cubre respuestas 500.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(athletes.router, prefix=settings.API_V1_PREFIX)
app.include_router(managed_athletes.router, prefix=settings.API_V1_PREFIX)
app.include_router(jump_analyses.router, prefix=settings.API_V1_PREFIX)
app.include_router(chat.router, prefix=settings.API_V1_PREFIX)
app.include_router(public.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
