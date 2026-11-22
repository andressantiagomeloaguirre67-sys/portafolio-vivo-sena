from rest_framework import serializers
from .models import ComentarioRevision, Reporte


class ComentarioRevisionSerializer(serializers.ModelSerializer):
    instructor_nombre = serializers.CharField(
        source="instructor.nombre_completo", read_only=True
    )
    respondido_por_nombre = serializers.CharField(
        source="respondido_por.nombre_completo", read_only=True, default=None
    )
    respondido_por_documento = serializers.CharField(
        source="respondido_por.documento", read_only=True, default=None
    )

    class Meta:
        model = ComentarioRevision
        fields = [
            "id",
            "proyecto",
            "instructor",
            "instructor_nombre",
            "numero_entrega_revisada",
            "comentario_instructor",
            "fecha_comentario",
            "respuesta_grupo",
            "respondido_por",
            "respondido_por_nombre",
            "respondido_por_documento",
            "fecha_respuesta",
            "corregido_en_entrega",
        ]
        read_only_fields = [
            "id",
            "instructor",
            "instructor_nombre",
            "fecha_comentario",
            "respondido_por",
            "respondido_por_nombre",
            "respondido_por_documento",
            "fecha_respuesta",
        ]


class CrearComentarioInstructorSerializer(serializers.Serializer):
    comentario_instructor = serializers.CharField(min_length=5)


class ResponderComentarioGrupoSerializer(serializers.Serializer):
    respuesta_grupo = serializers.CharField(
        min_length=3,
        help_text="Ej: 'Gracias profe, ya se corrigió en esta subida.'",
    )


class ReporteSerializer(serializers.ModelSerializer):
    proyecto_titulo = serializers.CharField(
        source="proyecto.titulo", read_only=True
    )
    reportado_por_nombre = serializers.CharField(
        source="reportado_por.nombre_completo", read_only=True
    )
    resuelto_por_nombre = serializers.CharField(
        source="resuelto_por.nombre_completo", read_only=True, default=None
    )

    class Meta:
        model = Reporte
        fields = [
            "id",
            "proyecto",
            "proyecto_titulo",
            "reportado_por",
            "reportado_por_nombre",
            "motivo",
            "estado",
            "nota_resolucion",
            "resuelto_por",
            "resuelto_por_nombre",
            "creado_en",
            "resuelto_en",
        ]
        read_only_fields = [
            "id",
            "reportado_por",
            "reportado_por_nombre",
            "estado",
            "nota_resolucion",
            "resuelto_por",
            "resuelto_por_nombre",
            "creado_en",
            "resuelto_en",
        ]


class CrearReporteSerializer(serializers.Serializer):
    proyecto = serializers.UUIDField()
    motivo = serializers.CharField(min_length=10)


class ResolverReporteSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[
            (Reporte.EstadoReporte.PROYECTO_RETIRADO, "Retirar Proyecto del Feed"),
            (Reporte.EstadoReporte.DESCARTADO, "Descartar Reporte"),
        ]
    )
    nota_resolucion = serializers.CharField(min_length=5)
