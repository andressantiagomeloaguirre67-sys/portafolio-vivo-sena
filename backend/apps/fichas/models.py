"""
Módulo 2: Fichas y Grupos Scrum (apps/fichas/models.py)
Reglas de Negocio:
- Un instructor puede tener MUCHAS fichas activas.
- Una ficha SOLO puede tener UN instructor activo por trimestre (`uq_un_solo_instructor_activo_por_ficha`).
- Mínimo 2 aprendices por Grupo Scrum.
- 1 Aprendiz = Máximo 1 Grupo Scrum (`OneToOneField`).
- Si un grupo se separa, el GrupoScrum SÍ se puede eliminar/disolver, pero los aprendices jamás se borran.
"""

import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class Ficha(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=20, unique=True, db_index=True)
    programa = models.CharField(
        max_length=150, default="Análisis y Desarrollo de Software (ADSO)"
    )
    jornada = models.CharField(max_length=20, default="DIURNA")
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fichas"
        verbose_name = "Ficha"
        verbose_name_plural = "Fichas"
        ordering = ["numero"]

    def __str__(self) -> str:
        return f"Ficha {self.numero} - {self.programa}"

    @property
    def instructor_activo(self):
        asignacion = (
            self.asignaciones.filter(activa=True)
            .select_related("instructor")
            .first()
        )
        return asignacion.instructor if asignacion else None


class AsignacionInstructor(models.Model):
    """
    - Un instructor puede tener MUCHAS fichas activas.
    - Una ficha SOLO puede tener UN instructor activo por trimestre.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(
        Ficha, on_delete=models.CASCADE, related_name="asignaciones"
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fichas_asignadas",
        limit_choices_to={"rol": "INSTRUCTOR"},
    )
    trimestre = models.CharField(max_length=30, help_text="Ej: 2026-Trimestre-3")
    activa = models.BooleanField(default=True, db_index=True)
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "asignaciones_instructor"
        verbose_name = "Asignación de Instructor"
        verbose_name_plural = "Asignaciones de Instructores"
        constraints = [
            models.UniqueConstraint(
                fields=["ficha"],
                condition=Q(activa=True),
                name="uq_un_solo_instructor_activo_por_ficha",
            )
        ]

    def __str__(self) -> str:
        estado = "ACTIVA" if self.activa else "HISTÓRICA"
        return f"Ficha {self.ficha.numero} -> {self.instructor.nombre_completo} ({self.trimestre} - {estado})"


class Matricula(models.Model):
    """Relaciona al aprendiz con su ficha."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    aprendiz = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # Prohibido borrar aprendices
        related_name="matriculas",
        limit_choices_to={"rol": "APRENDIZ"},
    )
    ficha = models.ForeignKey(
        Ficha, on_delete=models.PROTECT, related_name="matriculas"
    )
    activa = models.BooleanField(default=True)
    fecha_matricula = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "matriculas"
        verbose_name = "Matrícula"
        verbose_name_plural = "Matrículas"
        constraints = [
            models.UniqueConstraint(
                fields=["aprendiz"],
                condition=Q(activa=True),
                name="uq_una_matricula_activa_por_aprendiz",
            )
        ]

    def __str__(self) -> str:
        return f"{self.aprendiz.nombre_completo} -> Ficha {self.ficha.numero}"


class GrupoScrum(models.Model):
    """
    Grupo Scrum dentro de una ficha.
    - Mínimo 2 aprendices activos (validado en servicio/carga masiva).
    - Si el grupo se separa, el grupo SÍ se puede eliminar/disolver.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ficha = models.ForeignKey(
        Ficha, on_delete=models.CASCADE, related_name="grupos_scrum"
    )
    nombre_grupo = models.CharField(max_length=100, help_text="Ej: Grupo Scrum 1")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "grupos_scrum"
        verbose_name = "Grupo Scrum"
        verbose_name_plural = "Grupos Scrum"
        ordering = ["nombre_grupo"]
        constraints = [
            models.UniqueConstraint(
                fields=["ficha", "nombre_grupo"],
                name="uq_nombre_grupo_por_ficha",
            )
        ]

    def __str__(self) -> str:
        return f"{self.nombre_grupo} (Ficha {self.ficha.numero})"


class MiembroGrupoScrum(models.Model):
    """
    Une a cada aprendiz con su Grupo Scrum.
    - Ningún aprendiz puede estar en más de 1 grupo (`OneToOneField`).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grupo = models.ForeignKey(
        GrupoScrum, on_delete=models.CASCADE, related_name="miembros"
    )
    aprendiz = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="miembro_grupo_scrum",
        limit_choices_to={"rol": "APRENDIZ"},
    )
    fecha_ingreso = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "miembros_grupo_scrum"
        verbose_name = "Miembro de Grupo Scrum"
        verbose_name_plural = "Miembros de Grupos Scrum"

    def __str__(self) -> str:
        return f"{self.aprendiz.nombre_completo} en {self.grupo.nombre_grupo}"


class CargaMasiva(models.Model):
    """
    Registra el Excel/CSV de aprendices y grupos, guardando alertas si un nombre
    completo o documento aparece repetido en varios grupos o si un grupo tiene < 2 miembros.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    ficha = models.ForeignKey(
        Ficha, on_delete=models.CASCADE, related_name="cargas"
    )
    archivo = models.CharField(max_length=500)
    estado = models.CharField(max_length=25, default="PENDIENTE")
    alertas_duplicados = models.JSONField(default=list)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cargas_masivas"
        verbose_name = "Carga Masiva de Ficha"
        verbose_name_plural = "Cargas Masivas de Fichas"
        ordering = ["-creado_en"]
