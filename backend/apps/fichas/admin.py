from django.contrib import admin
from .models import (
    AsignacionInstructor,
    CargaMasiva,
    Ficha,
    GrupoScrum,
    Matricula,
    MiembroGrupoScrum,
)


@admin.register(Ficha)
class FichaAdmin(admin.ModelAdmin):
    list_display = ("numero", "programa", "jornada", "activa", "creada_en")
    search_fields = ("numero", "programa")
    list_filter = ("jornada", "activa")


@admin.register(AsignacionInstructor)
class AsignacionInstructorAdmin(admin.ModelAdmin):
    list_display = ("ficha", "instructor", "trimestre", "activa", "fecha_inicio", "fecha_fin")
    list_filter = ("activa", "trimestre")


@admin.register(Matricula)
class MatriculaAdmin(admin.ModelAdmin):
    list_display = ("aprendiz", "ficha", "activa", "fecha_matricula")
    list_filter = ("activa", "ficha")


@admin.register(GrupoScrum)
class GrupoScrumAdmin(admin.ModelAdmin):
    list_display = ("nombre_grupo", "ficha", "creado_en")
    list_filter = ("ficha",)


@admin.register(MiembroGrupoScrum)
class MiembroGrupoScrumAdmin(admin.ModelAdmin):
    list_display = ("aprendiz", "grupo", "fecha_ingreso")


@admin.register(CargaMasiva)
class CargaMasivaAdmin(admin.ModelAdmin):
    list_display = ("ficha", "instructor", "archivo", "estado", "creado_en")
    list_filter = ("estado",)
