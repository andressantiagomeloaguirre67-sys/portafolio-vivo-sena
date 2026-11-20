from rest_framework import serializers
from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario
from .models import (
    AsignacionInstructor,
    Ficha,
    GrupoScrum,
    MiembroGrupoScrum,
)


class MiembroGrupoScrumSerializer(serializers.ModelSerializer):
    aprendiz_id = serializers.UUIDField(source="aprendiz.id", read_only=True)
    documento = serializers.CharField(source="aprendiz.documento", read_only=True)
    nombre_completo = serializers.CharField(
        source="aprendiz.nombre_completo", read_only=True
    )
    correo = serializers.EmailField(source="aprendiz.correo", read_only=True)
    estado_cuenta = serializers.CharField(
        source="aprendiz.estado_cuenta", read_only=True
    )

    class Meta:
        model = MiembroGrupoScrum
        fields = [
            "id",
            "aprendiz_id",
            "documento",
            "nombre_completo",
            "correo",
            "estado_cuenta",
            "rol_scrum",
            "activo",
            "fecha_ingreso",
            "fecha_fin",
        ]


class GrupoScrumSerializer(serializers.ModelSerializer):
    miembros = serializers.SerializerMethodField()
    historial_miembros = serializers.SerializerMethodField()
    proyecto_id = serializers.SerializerMethodField()
    proyecto_titulo = serializers.SerializerMethodField()
    proyecto_descripcion = serializers.SerializerMethodField()
    proyecto_estado = serializers.SerializerMethodField()
    proyecto_estado_originalidad = serializers.SerializerMethodField()
    cantidad_aprendices_activos = serializers.SerializerMethodField()
    cumple_minimo_aprendices = serializers.SerializerMethodField()

    class Meta:
        model = GrupoScrum
        fields = [
            "id",
            "ficha",
            "nombre_grupo",
            "estado",
            "archivado_en",
            "creado_en",
            "cantidad_aprendices_activos",
            "cumple_minimo_aprendices",
            "miembros",
            "historial_miembros",
            "proyecto_id",
            "proyecto_titulo",
            "proyecto_descripcion",
            "proyecto_estado",
            "proyecto_estado_originalidad",
        ]
        read_only_fields = fields

    def _miembros_activos(self, obj: GrupoScrum):
        if hasattr(obj, "_prefetched_objects_cache") and "miembros" in obj._prefetched_objects_cache:
            return [m for m in obj.miembros.all() if m.activo]
        return list(obj.miembros.filter(activo=True).select_related("aprendiz"))

    def _miembros_historicos(self, obj: GrupoScrum):
        if hasattr(obj, "_prefetched_objects_cache") and "miembros" in obj._prefetched_objects_cache:
            return [m for m in obj.miembros.all() if not m.activo]
        return list(obj.miembros.filter(activo=False).select_related("aprendiz"))

    def get_miembros(self, obj: GrupoScrum):
        return MiembroGrupoScrumSerializer(self._miembros_activos(obj), many=True).data

    def get_historial_miembros(self, obj: GrupoScrum):
        return MiembroGrupoScrumSerializer(self._miembros_historicos(obj), many=True).data

    def get_proyecto_id(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return str(proyecto.id) if proyecto else None

    def get_proyecto_titulo(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return proyecto.titulo if proyecto else None

    def get_proyecto_descripcion(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return proyecto.introduccion if proyecto else None

    def get_proyecto_estado(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return proyecto.estado if proyecto else None

    def get_proyecto_estado_originalidad(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        if not proyecto:
            return "SIN_VALIDAR"
        return proyecto.estado_originalidad or "SIN_VALIDAR"

    def get_cantidad_aprendices_activos(self, obj: GrupoScrum) -> int:
        return sum(
            1
            for m in self._miembros_activos(obj)
            if m.aprendiz.estado_cuenta != EstadoCuenta.SUSPENDIDO
        )

    def get_cumple_minimo_aprendices(self, obj: GrupoScrum) -> bool:
        return self.get_cantidad_aprendices_activos(obj) >= 2


class AsignacionInstructorSerializer(serializers.ModelSerializer):
    instructor_documento = serializers.CharField(
        source="instructor.documento", read_only=True
    )
    instructor_nombre = serializers.CharField(
        source="instructor.nombre_completo", read_only=True
    )
    instructor_correo = serializers.EmailField(
        source="instructor.correo", read_only=True
    )
    ficha_numero = serializers.CharField(source="ficha.numero", read_only=True)

    class Meta:
        model = AsignacionInstructor
        fields = [
            "id",
            "ficha",
            "ficha_numero",
            "instructor",
            "instructor_documento",
            "instructor_nombre",
            "instructor_correo",
            "trimestre",
            "activa",
            "fecha_inicio",
            "fecha_fin",
        ]
        read_only_fields = fields


class FichaSerializer(serializers.ModelSerializer):
    instructor_activo = serializers.SerializerMethodField()
    trimestre_actual = serializers.SerializerMethodField()
    total_grupos_scrum = serializers.SerializerMethodField()
    total_grupos_publicados = serializers.SerializerMethodField()
    total_proyectos = serializers.SerializerMethodField()
    total_aprendices_activos = serializers.SerializerMethodField()
    total_aprendices_suspendidos = serializers.SerializerMethodField()
    total_aprendices_con_equipo = serializers.SerializerMethodField()
    total_aprendices_sin_equipo = serializers.SerializerMethodField()

    class Meta:
        model = Ficha
        fields = [
            "id",
            "numero",
            "programa",
            "jornada",
            "activa",
            "creada_en",
            "instructor_activo",
            "trimestre_actual",
            "total_grupos_scrum",
            "total_grupos_publicados",
            "total_proyectos",
            "total_aprendices_activos",
            "total_aprendices_suspendidos",
            "total_aprendices_con_equipo",
            "total_aprendices_sin_equipo",
        ]
        read_only_fields = ["id", "creada_en"]

    def get_instructor_activo(self, obj: Ficha):
        inst = obj.instructor_activo
        if not inst:
            return None
        return {
            "id": str(inst.id),
            "documento": inst.documento,
            "nombre_completo": inst.nombre_completo,
            "correo": inst.correo,
        }

    def get_trimestre_actual(self, obj: Ficha):
        asignacion = obj.asignaciones.filter(activa=True).first()
        return asignacion.trimestre if asignacion else None

    def get_total_grupos_scrum(self, obj: Ficha) -> int:
        return obj.grupos_scrum.exclude(estado=GrupoScrum.EstadoGrupo.ARCHIVADO).count()

    def get_total_grupos_publicados(self, obj: Ficha) -> int:
        return obj.grupos_scrum.filter(estado=GrupoScrum.EstadoGrupo.PUBLICADO).count()

    def get_total_proyectos(self, obj: Ficha) -> int:
        if not hasattr(obj, "proyectos"):
            return 0
        return obj.proyectos.filter(
            grupo_scrum__estado=GrupoScrum.EstadoGrupo.PUBLICADO
        ).exclude(
            estado__in=["ELIMINADO_POR_GRUPO", "RETIRADO_INSTRUCTOR"]
        ).count()

    def get_total_aprendices_activos(self, obj: Ficha) -> int:
        return (
            obj.matriculas.filter(activa=True)
            .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
            .count()
        )

    def get_total_aprendices_suspendidos(self, obj: Ficha) -> int:
        return obj.matriculas.filter(
            activa=True, aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO
        ).count()

    def get_total_aprendices_con_equipo(self, obj: Ficha) -> int:
        return (
            MiembroGrupoScrum.objects.filter(
                ficha=obj,
                activo=True,
                aprendiz__matriculas__ficha=obj,
                aprendiz__matriculas__activa=True,
            )
            .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
            .values("aprendiz_id")
            .distinct()
            .count()
        )

    def get_total_aprendices_sin_equipo(self, obj: Ficha) -> int:
        activos = self.get_total_aprendices_activos(obj)
        con_equipo = self.get_total_aprendices_con_equipo(obj)
        return max(0, activos - con_equipo)


class RotarInstructorSerializer(serializers.Serializer):
    instructor_id = serializers.UUIDField()
    trimestre = serializers.CharField(max_length=30)

    def validate_instructor_id(self, value):
        instructor = Usuario.objects.filter(
            id=value, rol=RolUsuario.INSTRUCTOR, is_active=True
        ).first()
        if not instructor:
            raise serializers.ValidationError(
                "No existe un instructor activo con ese ID."
            )
        return value


class RegistrarAprendizIndividualSerializer(serializers.Serializer):
    nombre_completo = serializers.CharField(max_length=180)
    documento = serializers.CharField(max_length=30)
    correo = serializers.EmailField()
    grupo_scrum = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )


class IntegranteEquipoInputSerializer(serializers.Serializer):
    aprendiz_id = serializers.UUIDField()
    rol_scrum = serializers.ChoiceField(
        choices=MiembroGrupoScrum.RolScrum.choices,
        default=MiembroGrupoScrum.RolScrum.DEVELOPER,
        required=False,
    )


class CrearEquipoScrumSerializer(serializers.Serializer):
    nombre_grupo = serializers.CharField(max_length=100)
    proyecto_titulo = serializers.CharField(max_length=150)
    proyecto_descripcion = serializers.CharField(min_length=10)
    estado = serializers.ChoiceField(
        choices=[
            (GrupoScrum.EstadoGrupo.BORRADOR, "Borrador"),
            (GrupoScrum.EstadoGrupo.PUBLICADO, "Publicado"),
        ],
        default=GrupoScrum.EstadoGrupo.BORRADOR,
        required=False,
    )
    integrantes = IntegranteEquipoInputSerializer(many=True, min_length=2)


class AgregarIntegranteEquipoSerializer(serializers.Serializer):
    aprendiz_id = serializers.UUIDField()
    rol_scrum = serializers.ChoiceField(
        choices=MiembroGrupoScrum.RolScrum.choices,
        default=MiembroGrupoScrum.RolScrum.DEVELOPER,
        required=False,
    )


class MoverIntegranteEquipoSerializer(serializers.Serializer):
    aprendiz_id = serializers.UUIDField()
    grupo_destino_id = serializers.UUIDField()
    rol_scrum = serializers.ChoiceField(
        choices=MiembroGrupoScrum.RolScrum.choices,
        default=MiembroGrupoScrum.RolScrum.DEVELOPER,
        required=False,
    )


class CambiarRolIntegranteSerializer(serializers.Serializer):
    aprendiz_id = serializers.UUIDField()
    rol_scrum = serializers.ChoiceField(choices=MiembroGrupoScrum.RolScrum.choices)


class CambiarEstadoEquipoSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(
        choices=[
            (GrupoScrum.EstadoGrupo.BORRADOR, "Borrador"),
            (GrupoScrum.EstadoGrupo.PUBLICADO, "Publicado"),
        ]
    )
