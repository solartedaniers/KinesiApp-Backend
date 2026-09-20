from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import athletes, jump_analyses, users
from app.core.config import settings
from app.core.database import Base, engine
from app.core.exceptions import AppException, app_exception_handler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # ponytail: create_all en vez de migraciones, agregar Alembic si el esquema empieza a versionarse
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.add_exception_handler(AppException, app_exception_handler)

app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(athletes.router, prefix=settings.API_V1_PREFIX)
app.include_router(jump_analyses.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
