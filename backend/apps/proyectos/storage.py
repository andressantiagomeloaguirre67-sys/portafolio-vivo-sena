"""
Integración de Almacenamiento S3 / MinIO y Sandbox para el Módulo 3 (apps/proyectos/storage.py).
Regla 4.3:
- Aloja únicamente la versión más reciente de cada proyecto en el bucket `proyectos-actuales-sena`.
- Soporta generación de URLs firmadas (Presigned URLs) para subida directa a MinIO/S3
  y sincronización automática con el directorio aislado del Sandbox.
"""

from pathlib import Path
from django.conf import settings


def obtener_cliente_s3():
    """Retorna un cliente boto3 configurado hacia MinIO/S3 si boto3 está instalado."""
    try:
        import boto3
        from botocore.client import Config

        return boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ROOT_USER,
            aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
            config=Config(signature_version="s3v4", connect_timeout=2, read_timeout=2),
            region_name="us-east-1",
        )
    except Exception:
        return None


def generar_url_firmada_subida_zip(proyecto_id: str, nombre_archivo: str = "entrega_actual.zip") -> dict:
    """
    Genera una URL firmada (Presigned PUT URL) para subir el nuevo .zip que reemplazará
    la entrega anterior del proyecto, junto con el endpoint local de respaldo.
    """
    object_key = f"proyectos/{proyecto_id}/entrega_mas_reciente.zip"
    s3 = obtener_cliente_s3()

    if s3 is not None:
        try:
            url_firmada = s3.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": settings.MINIO_BUCKET_PROYECTOS,
                    "Key": object_key,
                    "ContentType": "application/zip",
                },
                ExpiresIn=900,
            )
            return {
                "modo_almacenamiento": "MINIO_S3_PRESIGNED",
                "bucket": settings.MINIO_BUCKET_PROYECTOS,
                "object_key": object_key,
                "upload_url": url_firmada,
                "confirm_url": f"/api/v1/proyectos/{proyecto_id}/confirmar-subida/",
                "expira_en_segundos": 900,
            }
        except Exception:
            pass

    return {
        "modo_almacenamiento": "SANDBOX_DIRECTO",
        "bucket": settings.MINIO_BUCKET_PROYECTOS,
        "object_key": object_key,
        "upload_url": "/api/v1/proyectos/mi-grupo/subir-codigo/",
        "confirm_url": f"/api/v1/proyectos/{proyecto_id}/confirmar-subida/",
        "expira_en_segundos": 900,
    }


def eliminar_version_anterior_minio(proyecto_id: str) -> bool:
    """
    Elimina cualquier objeto previo del proyecto en el bucket de MinIO/S3 para garantizar
    cero acumulación de versiones antiguas.
    """
    s3 = obtener_cliente_s3()
    if s3 is None:
        return False
    try:
        objetos = s3.list_objects_v2(
            Bucket=settings.MINIO_BUCKET_PROYECTOS,
            Prefix=f"proyectos/{proyecto_id}/",
        )
        for obj in objetos.get("Contents", []):
            s3.delete_object(
                Bucket=settings.MINIO_BUCKET_PROYECTOS,
                Key=obj["Key"],
            )
        return True
    except Exception:
        return False
