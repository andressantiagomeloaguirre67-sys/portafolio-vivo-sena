from rest_framework import serializers
from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario
from .models import (
    AsignacionInstructor,
    CargaMasiva,
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
            "fecha_ingreso",
        ]


class GrupoScrumSerializer(serializers.ModelSerializer):
    miembros = MiembroGrupoScrumSerializer(many=True, read_only=True)
    proyecto_id = serializers.SerializerMethodField()
    proyecto_titulo = serializers.SerializerMethodField()
    proyecto_estado = serializers.SerializerMethodField()
    cantidad_aprendices_activos = serializers.SerializerMethodField()
    cumple_minimo_aprendices = serializers.SerializerMethodField()

    class Meta:
        model = GrupoScrum
        fields = [
            "id",
            "ficha",
            "nombre_grupo",
            "creado_en",
            "cantidad_aprendices_activos",
            "cumple_minimo_aprendices",
            "miembros",
            "proyecto_id",
            "proyecto_titulo",
            "proyecto_estado",
        ]
        read_only_fields = [
            "id",
            "creado_en",
            "cantidad_aprendices_activos",
            "cumple_minimo_aprendices",
            "miembros",
            "proyecto_id",
            "proyecto_titulo",
            "proyecto_estado",
        ]

    def get_proyecto_id(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return str(proyecto.id) if proyecto else None

    def get_proyecto_titulo(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return proyecto.titulo if proyecto else None

    def get_proyecto_estado(self, obj: GrupoScrum):
        proyecto = getattr(obj, "proyecto", None)
        return proyecto.estado if proyecto else None

    def get_cantidad_aprendices_activos(self, obj: GrupoScrum) -> int:
        return sum(
            1
            for m in obj.miembros.all()
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
    total_proyectos = serializers.SerializerMethodField()
    total_aprendices_activos = serializers.SerializerMethodField()
    total_aprendices_suspendidos = serializers.SerializerMethodField()

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
            "total_proyectos",
            "total_aprendices_activos",
            "total_aprendices_suspendidos",
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
        return obj.grupos_scrum.count()

    def get_total_proyectos(self, obj: Ficha) -> int:
        return obj.proyectos.count() if hasattr(obj, "proyectos") else 0

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


class ConformarGrupoScrumSerializer(serializers.Serializer):
    nombre_grupo = serializers.CharField(max_length=100)
    documentos_aprendices = serializers.ListField(
        child=serializers.CharField(max_length=30),
        min_length=2,
        help_text="Lista de documentos de los aprendices activos (mínimo 2).",
    )


class RegistroAprendizGrupoSerializer(serializers.Serializer):
    nombre_completo = serializers.CharField(max_length=180)
    documento = serializers.CharField(max_length=30)
    correo = serializers.EmailField()
    grupo_scrum = serializers.CharField(max_length=100)


class CargaMasivaFichaRequestSerializer(serializers.Serializer):
    nombre_archivo = serializers.CharField(
        max_length=255, default="carga_ficha.xlsx"
    )
    registros = RegistroAprendizGrupoSerializer(many=True, allow_empty=False)


class CargaMasivaSerializer(serializers.ModelSerializer):
    instructor_nombre = serializers.CharField(
        source="instructor.nombre_completo", read_only=True
    )

    class Meta:
        model = CargaMasiva
        fields = [
            "id",
            "ficha",
            "instructor",
            "instructor_nombre",
            "archivo",
            "estado",
            "alertas_duplicados",
            "creado_en",
        ]
