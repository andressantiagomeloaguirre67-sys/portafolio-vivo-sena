"""
Módulo 3: Proyectos y Feed (apps/proyectos/models.py)
Reglas de Negocio:
- Relación 1 a 1 con GrupoScrum (5 grupos = máximo 5 proyectos).
- Solo aloja 1 archivo (el más reciente) en `ruta_codigo_actual` reemplazando el anterior en MinIO/S3.
- Incluye vector semántico (`embedding_idea`) para que ningún proyecto repita idea en el SENA.
- Bitácora inmutable (`HistorialProyecto`) que registra quién del grupo realizó cada acción con fecha y hora exacta.
"""

import uuid
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.fichas.models import Ficha, GrupoScrum


class Proyecto(models.Model):
    """
    - Relación 1 a 1 con GrupoScrum (5 grupos = máximo 5 proyectos).
    - Solo aloja 1 archivo (el más reciente) en ruta_codigo_actual.
    - Incluye vector semántico (768 dimensiones en PostgreSQL) para que ningún proyecto repita idea en el SENA.
    """

    class EstadoProyecto(models.TextChoices):
        DEFINIENDO_IDEA = "DEFINIENDO_IDEA", "Definiendo idea con Agente"
        IDEA_APROBADA = "IDEA_APROBADA", "Idea única aprobada (Sin código aún)"
        PUBLICADO = "PUBLICADO", "Publicado en el Feed"
        ELIMINADO_POR_GRUPO = "ELIMINADO_POR_GRUPO", "Retirado por el grupo"
        RETIRADO_INSTRUCTOR = "RETIRADO_INSTRUCTOR", "Retirado por el instructor"

    class Visibilidad(models.TextChoices):
        FICHA = "FICHA", "Solo la ficha"
        PUBLICO = "PUBLICO", "Público"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(
        Ficha, on_delete=models.PROTECT, related_name="proyectos"
    )
    grupo_scrum = models.OneToOneField(
        GrupoScrum, on_delete=models.CASCADE, related_name="proyecto"
    )

    # Identidad única del proyecto (Ningún proyecto puede repetir título ni idea)
    titulo = models.CharField(max_length=150, unique=True, db_index=True)
    introduccion = models.TextField()
    embedding_idea = ArrayField(
        models.FloatField(), size=768, null=True, blank=True
    )  # Vector semántico en PostgreSQL para comparar que no se repita la idea
    tecnologias = ArrayField(
        models.CharField(max_length=40), default=list, blank=True
    )

    # Alojamiento ÚNICO de la versión más reciente (reemplaza la anterior en MinIO/S3)
    ruta_codigo_actual = models.CharField(max_length=500, blank=True)
    punto_entrada = models.CharField(max_length=255, default="index.html")
    numero_entrega_actual = models.PositiveIntegerField(default=0)
    estado_procesamiento_zip = models.CharField(
        max_length=20, default="SIN_SUBIR"
    )
    ultimo_error_zip = models.TextField(blank=True)

    estado = models.CharField(
        max_length=25,
        choices=EstadoProyecto.choices,
        default=EstadoProyecto.DEFINIENDO_IDEA,
    )
    visibilidad = models.CharField(
        max_length=15,
        choices=Visibilidad.choices,
        default=Visibilidad.FICHA,
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "proyectos"
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"
        ordering = ["-actualizado_en"]

    def __str__(self) -> str:
        return f"{self.titulo} ({self.grupo_scrum.nombre_grupo})"

    @property
    def url_ejecucion_sandbox(self) -> str | None:
        if not self.ruta_codigo_actual or self.estado != self.EstadoProyecto.PUBLICADO:
            return None
        return f"/sandbox/{self.id}/{self.punto_entrada.lstrip('/')}"


class HistorialProyecto(models.Model):
    """
    Bitácora inmutable ('Historias'): deja constancia de QUIÉN del grupo
    subió el proyecto, actualizó el código, respondió un comentario o lo eliminó,
    con fecha y hora exacta.
    """

    class TipoAccion(models.TextChoices):
        REGISTRO_IDEA = "REGISTRO_IDEA", "Registró la idea del proyecto"
        SUBIO_CODIGO = "SUBIO_CODIGO", "Subió / Reemplazó el código del proyecto"
        RESPUESTA_COMENTARIO = "RESPUESTA_COMENTARIO", "Respondió a un comentario del instructor"
        ELIMINO_PROYECTO = "ELIMINO_PROYECTO", "Eliminó / Retiró el proyecto"
        CAMBIO_ESTADO = "CAMBIO_ESTADO", "Cambió estado o visibilidad"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proyecto = models.ForeignKey(
        Proyecto, on_delete=models.CASCADE, related_name="historial"
    )
    realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    accion = models.CharField(max_length=25, choices=TipoAccion.choices)
    numero_entrega = models.PositiveIntegerField(default=0)
    descripcion_cambio = models.TextField(
        help_text="Nota de qué cambió o por qué se retiró"
    )
    fecha_hora = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "historial_proyectos"
        verbose_name = "Historial de Proyecto"
        verbose_name_plural = "Historiales de Proyectos"
        ordering = ["-fecha_hora"]

    def __str__(self) -> str:
        return (
            f"[{self.fecha_hora:%Y-%m-%d %H:%M}] {self.realizado_por.nombre_completo} "
            f"({self.realizado_por.documento}) -> {self.accion}"
        )
