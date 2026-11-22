"""
Tareas asíncronas Celery del Módulo 3: Proyectos (apps/proyectos/tasks.py)
Valida el paquete .zip, reemplaza la entrega única en el Sandbox/MinIO y registra en HistorialProyecto.
"""

from config.celery import app
from apps.usuarios.models import Usuario
from .models import HistorialProyecto, Proyecto
from .services import validar_y_reemplazar_entrega_unica
from .storage import eliminar_version_anterior_minio


def _shared_task_decorator(func):
    if app is not None:
        return app.task(name=f"proyectos.{func.__name__}")(func)
    return func


@_shared_task_decorator
def validar_y_publicar_entrega_task(
    proyecto_id: str,
    usuario_id: str,
    descripcion_cambio: str,
    punto_entrada: str = "index.html",
    codigo_html: str | None = None,
) -> dict:
    proyecto = Proyecto.objects.get(id=proyecto_id)
    usuario = Usuario.objects.get(id=usuario_id)

    eliminar_version_anterior_minio(str(proyecto.id))
    nueva_ruta = validar_y_reemplazar_entrega_unica(
        proyecto=proyecto,
        archivo_zip=None,
        codigo_html=codigo_html,
        punto_entrada=punto_entrada,
    )

    nueva_entrega = proyecto.numero_entrega_actual + 1
    proyecto.ruta_codigo_actual = nueva_ruta
    proyecto.punto_entrada = punto_entrada
    proyecto.numero_entrega_actual = nueva_entrega
    proyecto.estado_procesamiento_zip = "LISTO"
    proyecto.ultimo_error_zip = ""
    proyecto.estado = Proyecto.EstadoProyecto.PUBLICADO
    proyecto.save(
        update_fields=[
            "ruta_codigo_actual",
            "punto_entrada",
            "numero_entrega_actual",
            "estado_procesamiento_zip",
            "ultimo_error_zip",
            "estado",
            "actualizado_en",
        ]
    )

    HistorialProyecto.objects.create(
        proyecto=proyecto,
        realizado_por=usuario,
        accion=HistorialProyecto.TipoAccion.SUBIO_CODIGO,
        numero_entrega=nueva_entrega,
        descripcion_cambio=descripcion_cambio,
    )

    return {
        "proyecto_id": str(proyecto.id),
        "numero_entrega_actual": nueva_entrega,
        "estado": proyecto.estado,
        "ruta_codigo_actual": nueva_ruta,
    }
