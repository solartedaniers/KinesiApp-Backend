from fastapi import FastAPI

from app.api.routes import athletes, auth, jump_analyses, users
from app.core.config import settings
from app.core.exceptions import AppException, app_exception_handler

# El esquema lo crea Alembic (alembic upgrade head), no la app al arrancar.
# Ver backend/README.md para el orden de arranque.
app = FastAPI(title=settings.PROJECT_NAME)

app.add_exception_handler(AppException, app_exception_handler)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(athletes.router, prefix=settings.API_V1_PREFIX)
app.include_router(jump_analyses.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
