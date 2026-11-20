"""
Módulo 4: Revisiones, Comentarios y Reportes (apps/revisiones/models.py)
Reglas de Negocio:
- `ComentarioRevision`: Mantiene el historial completo de comentarios del instructor y las
  respuestas del Grupo Scrum sin guardar repositorios viejos en disco.
- `ConsultaEscaladaInstructor`: Modelo histórico de solo archivo (regla No-Delete). El
  escalamiento de Aegis al instructor fue eliminado; los registros previos se conservan
  marcados como `archivada_por_cambio_de_politica` y no se muestran ni se cuentan.
- `Reporte`: Permite reportar proyectos para moderación y retirarlos si incumplen las normas SENA.
"""

import uuid
from django.conf import settings
from django.db import models

from apps.fichas.models import Ficha, GrupoScrum
from apps.proyectos.models import Proyecto


class ComentarioRevision(models.Model):
    """
    Mantiene el historial de comentarios del instructor y las respuestas del Grupo Scrum
    ('Sí profe, gracias, ya se corrigió y se subió el nuevo código'), sin guardar código viejo.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proyecto = models.ForeignKey(
        Proyecto, on_delete=models.CASCADE, related_name="comentarios"
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comentarios_realizados",
    )
    numero_entrega_revisada = models.PositiveIntegerField(default=1)
    comentario_instructor = models.TextField()
    fecha_comentario = models.DateTimeField(auto_now_add=True)

    # Respuesta del Grupo Scrum cuando corrigen y suben el nuevo archivo
    respuesta_grupo = models.TextField(blank=True)
    respondido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="respuestas_comentarios",
    )
    fecha_respuesta = models.DateTimeField(null=True, blank=True)
    corregido_en_entrega = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "comentarios_revision"
        verbose_name = "Comentario de Revisión"
        verbose_name_plural = "Comentarios de Revisión"
        ordering = ["-fecha_comentario"]

    def __str__(self) -> str:
        return (
            f"Comentario en '{self.proyecto.titulo}' (Entrega #{self.numero_entrega_revisada}) "
            f"por {self.instructor.nombre_completo}"
        )


class ConsultaEscaladaInstructor(models.Model):
    """
    Registro histórico archivado (Regla No-Delete).
    Aegis opera de forma autónoma sin escalar consultas al instructor; esta tabla conserva
    únicamente el historial previo marcado como `archivada_por_cambio_de_politica`.
    """

    class EstadoConsulta(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente (histórico)"
        ATENDIDA = "ATENDIDA", "Atendida (histórico)"
        ARCHIVADA_POR_CAMBIO_DE_POLITICA = (
            "archivada_por_cambio_de_politica",
            "Archivada por cambio de política",
        )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(
        Ficha,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="consultas_escaladas",
    )
    grupo_scrum = models.ForeignKey(
        GrupoScrum,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="consultas_escaladas",
    )
    proyecto = models.ForeignKey(
        Proyecto,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="consultas_escaladas",
    )
    aprendiz = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    instructor_destino = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consultas_recibidas",
    )
    mensaje_original_aprendiz = models.TextField()
    motivo_escalado = models.CharField(
        max_length=120, default="Revisión de lógica / diagramas / alcance"
    )
    respuesta_instructor = models.TextField(blank=True)
    estado = models.CharField(
        max_length=40,
        choices=EstadoConsulta.choices,
        default=EstadoConsulta.ARCHIVADA_POR_CAMBIO_DE_POLITICA,
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    respondido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "consultas_escaladas_instructor"
        verbose_name = "Consulta Escalada al Instructor"
        verbose_name_plural = "Consultas Escaladas al Instructor"
        ordering = ["-creado_en"]

    def __str__(self) -> str:
        return (
            f"Consulta escalada de {self.aprendiz.nombre_completo} -> "
            f"{self.instructor_destino.nombre_completo} ({self.estado})"
        )


class Reporte(models.Model):
    """
    Tabla 12 del Modelo de Datos SENA:
    Permite reportar proyectos en el Feed y resolverlos por moderación del Instructor o Administrador.
    """

    class EstadoReporte(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente de revisión"
        PROYECTO_RETIRADO = "PROYECTO_RETIRADO", "Aceptado (Proyecto retirado del Feed)"
        DESCARTADO = "DESCARTADO", "Descartado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proyecto = models.ForeignKey(
        Proyecto, on_delete=models.CASCADE, related_name="reportes"
    )
    reportado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reportes_creados",
    )
    motivo = models.TextField()
    estado = models.CharField(
        max_length=25,
        choices=EstadoReporte.choices,
        default=EstadoReporte.PENDIENTE,
    )
    nota_resolucion = models.TextField(blank=True)
    resuelto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reportes_resueltos",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    resuelto_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reportes_proyectos"
        verbose_name = "Reporte de Proyecto"
        verbose_name_plural = "Reportes de Proyectos"
        ordering = ["-creado_en"]

    def __str__(self) -> str:
        return f"Reporte sobre '{self.proyecto.titulo}' ({self.estado})"
