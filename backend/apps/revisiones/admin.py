from django.contrib import admin
from .models import ComentarioRevision, Reporte


@admin.register(ComentarioRevision)
class ComentarioRevisionAdmin(admin.ModelAdmin):
    list_display = (
        "proyecto",
        "instructor",
        "numero_entrega_revisada",
        "fecha_comentario",
        "respondido_por",
        "corregido_en_entrega",
    )
    list_filter = ("numero_entrega_revisada",)


@admin.register(Reporte)
class ReporteAdmin(admin.ModelAdmin):
    list_display = (
        "proyecto",
        "reportado_por",
        "estado",
        "resuelto_por",
        "creado_en",
    )
    list_filter = ("estado",)
