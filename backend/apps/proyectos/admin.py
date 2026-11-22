from django.contrib import admin
from .models import HistorialProyecto, Proyecto


@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = (
        "titulo",
        "ficha",
        "grupo_scrum",
        "estado",
        "numero_entrega_actual",
        "visibilidad",
        "actualizado_en",
    )
    list_filter = ("estado", "visibilidad", "ficha")
    search_fields = ("titulo", "introduccion")


@admin.register(HistorialProyecto)
class HistorialProyectoAdmin(admin.ModelAdmin):
    list_display = (
        "proyecto",
        "realizado_por",
        "accion",
        "numero_entrega",
        "fecha_hora",
    )
    list_filter = ("accion",)
    readonly_fields = (
        "proyecto",
        "realizado_por",
        "accion",
        "numero_entrega",
        "descripcion_cambio",
        "fecha_hora",
    )
