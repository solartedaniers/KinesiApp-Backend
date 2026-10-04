"""Move profile photos from data URLs in the database to the images bucket (avatar_url).

Revision ID: 151f2ecce8b2
Revises: d28e52f6d0b7

Las fotos existentes se suben al bucket de imágenes (S3_IMAGES_BUCKET) y en la base queda sólo su
URL pública. Si hay fotos y el almacenamiento no está configurado, la migración se detiene en vez
de perderlas. No usa las clases de la app (app/storage): una migración debe seguir funcionando
aunque ese código cambie después.
"""
import base64
import binascii
import uuid
from io import BytesIO
from typing import Sequence, Union
from urllib.parse import quote

from alembic import op
import sqlalchemy as sa


revision: str = "151f2ecce8b2"
down_revision: Union[str, None] = "d28e52f6d0b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("users", "athlete_profiles")
_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _upload_existing_avatars(connection) -> None:
    rows = {
        table: connection.execute(
            sa.text(f"SELECT id, avatar_data_url FROM {table} WHERE avatar_data_url IS NOT NULL")
        ).all()
        for table in _TABLES
    }
    if not any(rows.values()):
        return

    from app.core.config import settings

    secret = settings.AWS_SECRET_ACCESS_KEY.get_secret_value() if settings.AWS_SECRET_ACCESS_KEY else ""
    if not (settings.AWS_ENDPOINT_URL_S3 and settings.AWS_REGION and settings.AWS_ACCESS_KEY_ID and secret):
        raise RuntimeError(
            "There are profile photos stored as data URLs. Configure AWS_ENDPOINT_URL_S3, AWS_REGION, "
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY so this migration can move them to the images bucket."
        )

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.AWS_ENDPOINT_URL_S3,
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=secret,
        config=Config(s3={"addressing_style": "path"}),
    )
    public_base_url = f"{settings.AWS_ENDPOINT_URL_S3.rstrip('/')}/{settings.S3_IMAGES_BUCKET}/"
    for table, table_rows in rows.items():
        for row_id, data_url in table_rows:
            header, _, payload = data_url.partition(",")
            content_type = header.removeprefix("data:").removesuffix(";base64")
            try:
                content = base64.b64decode(payload, validate=True)
            except binascii.Error:
                # Un data URL corrupto no se puede mostrar de todos modos: se descarta
                continue
            key = f"avatars/{uuid.uuid4().hex}{_EXTENSIONS.get(content_type, '')}"
            client.put_object(Bucket=settings.S3_IMAGES_BUCKET, Key=key, Body=BytesIO(content), ContentType=content_type)
            connection.execute(
                sa.text(f"UPDATE {table} SET avatar_url = :url WHERE id = :id"),
                {"url": public_base_url + quote(key), "id": row_id},
            )


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("avatar_url", sa.String(length=500), nullable=True))
    _upload_existing_avatars(op.get_bind())
    for table in _TABLES:
        op.drop_column(table, "avatar_data_url")


def downgrade() -> None:
    # No vuelve a traer las fotos del bucket: los objetos quedan allí y las URLs se pierden
    for table in _TABLES:
        op.add_column(table, sa.Column("avatar_data_url", sa.Text(), nullable=True))
        op.drop_column(table, "avatar_url")
