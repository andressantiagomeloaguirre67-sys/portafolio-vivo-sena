"""
Tareas asíncronas Celery del Módulo 2: Fichas y Grupos Scrum (apps/fichas/tasks.py)
Permite procesar cargas masivas de archivos Excel/CSV en segundo plano vía Celery + Redis,
con respaldo síncrono automático.
"""

from config.celery import app
from apps.usuarios.models import Usuario
from .models import Ficha
from .services import procesar_carga_masiva_ficha


def _shared_task_decorator(func):
    if app is not None:
        return app.task(name=f"fichas.{func.__name__}")(func)
    return func


@_shared_task_decorator
def procesar_carga_masiva_ficha_task(
    ficha_id: str,
    instructor_id: str,
    registros: list[dict],
    nombre_archivo: str = "carga_ficha.xlsx",
) -> dict:
    ficha = Ficha.objects.get(id=ficha_id)
    instructor = Usuario.objects.get(id=instructor_id)
    carga, resultado = procesar_carga_masiva_ficha(
        ficha=ficha,
        instructor=instructor,
        registros=registros,
        nombre_archivo=nombre_archivo,
    )
    return {
        "carga_id": str(carga.id),
        "estado": carga.estado,
        "total_resultado": len(resultado),
    }
