"""Variables ficticias para toda la suite: le ganan al .env, así ninguna prueba toca Neon, Resend, la IA ni el bucket real."""
import os

# Sin API key de Resend, aunque el .env la tenga: si un test olvidara su correo falso, el envío
# fallaría con UnconfiguredEmailSender en vez de llamar a Resend
os.environ["RESEND_API_KEY"] = ""
os.environ.setdefault("OTP_EXPIRE_MINUTES", "10")
# Sin default en Settings: la app no arranca sin clave
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-with-enough-length")
# Postgres ficticio: los tests usan SQLite en memoria y, al ganarle al .env, nunca tocan Neon
os.environ.setdefault("POSTGRES_HOST", "postgres.test")
# IA ficticia: ninguna prueba llega a la IA real aunque el .env la tenga
os.environ["AI_SERVICE_URL"] = "http://ai.test"
os.environ["AI_SERVICE_TOKEN"] = "test-ai-service-token-with-32-characters"
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("POSTGRES_DB", "kinesiapp_test")
# Sin credenciales de almacenamiento, aunque el .env tenga las de Neon: si un test olvidara el
# fake, fallaría en vez de escribir en el bucket real
for _storage_variable in ("AWS_ENDPOINT_URL_S3", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
    os.environ[_storage_variable] = ""
