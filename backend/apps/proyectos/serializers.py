from rest_framework import serializers
from .models import HistorialProyecto, Proyecto


class HistorialProyectoSerializer(serializers.ModelSerializer):
    aprendiz_nombre = serializers.CharField(
        source="realizado_por.nombre_completo", read_only=True
    )
    aprendiz_documento = serializers.CharField(
        source="realizado_por.documento", read_only=True
    )
    aprendiz_rol = serializers.CharField(
        source="realizado_por.rol", read_only=True
    )

    class Meta:
        model = HistorialProyecto
        fields = [
            "id",
            "proyecto",
            "realizado_por",
            "aprendiz_nombre",
            "aprendiz_documento",
            "aprendiz_rol",
            "accion",
            "numero_entrega",
            "descripcion_cambio",
            "fecha_hora",
        ]
        read_only_fields = fields


class ProyectoFeedSerializer(serializers.ModelSerializer):
    ficha_numero = serializers.CharField(source="ficha.numero", read_only=True)
    ficha_programa = serializers.CharField(source="ficha.programa", read_only=True)
    nombre_grupo = serializers.CharField(
        source="grupo_scrum.nombre_grupo", read_only=True
    )
    integrantes = serializers.SerializerMethodField()
    url_ejecucion_sandbox = serializers.CharField(read_only=True)
    total_comentarios = serializers.SerializerMethodField()

    class Meta:
        model = Proyecto
        fields = [
            "id",
            "ficha",
            "ficha_numero",
            "ficha_programa",
            "grupo_scrum",
            "nombre_grupo",
            "integrantes",
            "titulo",
            "introduccion",
            "tecnologias",
            "punto_entrada",
            "numero_entrega_actual",
            "estado_procesamiento_zip",
            "ultimo_error_zip",
            "estado",
            "visibilidad",
            "url_ejecucion_sandbox",
            "total_comentarios",
            "actualizado_en",
        ]
        read_only_fields = fields

    def get_integrantes(self, obj: Proyecto):
        return [
            {
                "id": str(m.aprendiz.id),
                "nombre_completo": m.aprendiz.nombre_completo,
                "documento": m.aprendiz.documento,
                "estado_cuenta": m.aprendiz.estado_cuenta,
            }
            for m in obj.grupo_scrum.miembros.select_related("aprendiz").all()
        ]

    def get_total_comentarios(self, obj: Proyecto) -> int:
        if hasattr(obj, "_prefetched_objects_cache") and "comentarios" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["comentarios"])
        return obj.comentarios.count() if hasattr(obj, "comentarios") else 0


class ValidarIdeaProyectoSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=150)
    introduccion = serializers.CharField(min_length=15)


class RegistrarOActualizarIdeaProyectoSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=150)
    introduccion = serializers.CharField(min_length=15)
    tecnologias = serializers.ListField(
        child=serializers.CharField(max_length=40),
        required=False,
        default=list,
    )
    visibilidad = serializers.ChoiceField(
        choices=Proyecto.Visibilidad.choices,
        default=Proyecto.Visibilidad.FICHA,
    )


class ReemplazarCodigoProyectoSerializer(serializers.Serializer):
    punto_entrada = serializers.CharField(max_length=255, default="index.html")
    descripcion_cambio = serializers.CharField(
        min_length=5,
        help_text="Explicación breve de qué se subió o corrigió en esta entrega.",
    )


class RetirarProyectoInstructorSerializer(serializers.Serializer):
    motivo = serializers.CharField(
        min_length=10,
        help_text="Motivo obligatorio por el cual el instructor retira el proyecto del Feed.",
    )
