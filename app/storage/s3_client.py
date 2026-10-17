import boto3
from botocore.config import Config


def build_s3_client(endpoint_url: str, region: str, access_key_id: str, secret_access_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        # Neon sólo publica URLs path-style: su certificado no cubre <bucket>.<endpoint>
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )
