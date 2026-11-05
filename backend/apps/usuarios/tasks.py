"""
Tareas asíncronas Celery del Módulo 1: Usuarios (apps/usuarios/tasks.py)
Procesa el envío de invitaciones de activación y recuperación de clave por Gmail SMTP.
Incluye ejecución síncrona de respaldo si el broker Redis no está activo en desarrollo local.
"""

from config.celery import app
from .models import Usuario
from .services import enviar_correo_activacion_aprendiz


def _shared_task_decorator(func):
    if app is not None:
        return app.task(name=f"usuarios.{func.__name__}")(func)
    return func


@_shared_task_decorator
def enviar_correo_activacion_task(
    aprendiz_id: str,
    ficha_numero: str = "",
    nombre_grupo: str = "",
) -> bool:
    aprendiz = Usuario.objects.filter(id=aprendiz_id).first()
    if not aprendiz:
        return False
    return enviar_correo_activacion_aprendiz(
        aprendiz=aprendiz,
        ficha_numero=ficha_numero,
        nombre_grupo=nombre_grupo,
    )


def despachar_correo_activacion(
    aprendiz: Usuario,
    ficha_numero: str = "",
    nombre_grupo: str = "",
) -> bool:
    """
    Intenta encolar el envío en Celery/Redis; si el broker no está disponible,
    lo ejecuta de inmediato en el hilo actual para no perder ningún correo.
    """
    if hasattr(enviar_correo_activacion_task, "delay"):
        try:
            enviar_correo_activacion_task.delay(
                str(aprendiz.id), ficha_numero, nombre_grupo
            )
            return True
        except Exception:
            pass
    return enviar_correo_activacion_aprendiz(
        aprendiz=aprendiz,
        ficha_numero=ficha_numero,
        nombre_grupo=nombre_grupo,
    )
