from fastapi import APIRouter

from app.core.config import settings

# Sin auth: datos que el cliente web necesita antes de iniciar sesión o para páginas
# estáticas (ISR), idénticos para todos los usuarios
router = APIRouter(prefix="/public", tags=["public"])


@router.get("/video-consent")
def get_video_consent() -> dict[str, int]:
    # Versión vigente del texto de consentimiento: la que exige POST /jump-analyses/upload.
    # El cliente la lee de aquí en vez de fijarla en el build
    return {"version": settings.VIDEO_CONSENT_VERSION}


@router.get("/video-limits")
def get_video_limits() -> dict[str, int]:
    # El cliente valida el tamaño antes de subir con el mismo límite que aplica la API
    return {"max_size_bytes": settings.MAX_VIDEO_UPLOAD_BYTES}
