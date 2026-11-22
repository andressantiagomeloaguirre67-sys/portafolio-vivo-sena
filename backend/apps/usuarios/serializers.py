from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import EstadoCuenta, RolUsuario, Usuario


class UsuarioPerfilSerializer(serializers.ModelSerializer):
    ficha_activa = serializers.SerializerMethodField()
    grupo_scrum = serializers.SerializerMethodField()
    suspendido_por_nombre = serializers.CharField(
        source="suspendido_por.nombre_completo", read_only=True, default=None
    )

    class Meta:
        model = Usuario
        fields = [
            "id",
            "documento",
            "nombre_completo",
            "correo",
            "rol",
            "estado_cuenta",
            "is_active",
            "motivo_suspension",
            "fecha_suspension",
            "suspendido_por_nombre",
            "acepto_habeas_data",
            "creado_en",
            "ficha_activa",
            "grupo_scrum",
        ]
        read_only_fields = fields

    def get_ficha_activa(self, obj: Usuario):
        matricula = (
            obj.matriculas.filter(activa=True).select_related("ficha").first()
            if hasattr(obj, "matriculas")
            else None
        )
        if not matricula:
            return None
        return {
            "id": str(matricula.ficha.id),
            "numero": matricula.ficha.numero,
            "programa": matricula.ficha.programa,
            "jornada": matricula.ficha.jornada,
        }

    def get_grupo_scrum(self, obj: Usuario):
        miembro = getattr(obj, "miembro_grupo_scrum", None)
        if not miembro or not miembro.activo:
            return None
        return {
            "id": str(miembro.grupo.id),
            "nombre_grupo": miembro.grupo.nombre_grupo,
            "estado": miembro.grupo.estado,
            "rol_scrum": miembro.rol_scrum,
            "ficha_id": str(miembro.grupo.ficha_id),
        }


class LoginPorDocumentoSerializer(TokenObtainPairSerializer):
    """
    Autenticación JWT usando `documento` (o correo como respaldo) y `password`.
    Valida explícitamente si el aprendiz está PENDIENTE o SUSPENDIDO para dar un mensaje claro.
    """

    username_field = "documento"

    def validate(self, attrs):
        identificador = str(attrs.get("documento", "")).strip()
        password = attrs.get("password", "")

        usuario = Usuario.objects.filter(
            Q(documento=identificador) | Q(correo__iexact=identificador)
        ).first()

        if usuario:
            # Normalizar el campo documento si el usuario ingresó su correo
            attrs["documento"] = usuario.documento

            if usuario.estado_cuenta == EstadoCuenta.SUSPENDIDO:
                raise AuthenticationFailed(
                    f"Tu cuenta se encuentra SUSPENDIDA. Motivo registrado: {usuario.motivo_suspension}"
                )
            if usuario.estado_cuenta == EstadoCuenta.PENDIENTE:
                raise AuthenticationFailed(
                    "Tu cuenta está PENDIENTE de activación. Revisa el enlace enviado a tu correo Gmail."
                )
            if not usuario.check_password(password):
                raise AuthenticationFailed("Documento o contraseña incorrectos.")

        data = super().validate(attrs)
        data["usuario"] = UsuarioPerfilSerializer(self.user).data
        return data


class ActivarCuentaAprendizSerializer(serializers.Serializer):
    documento = serializers.CharField(max_length=30)
    token_activacion = serializers.CharField(max_length=120)
    password = serializers.CharField(write_only=True, min_length=8)
    acepto_habeas_data = serializers.BooleanField()

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def validate_acepto_habeas_data(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "Debes aceptar la política de tratamiento de datos (Habeas Data) para activar tu cuenta."
            )
        return value


class ReenviarActivacionSerializer(serializers.Serializer):
    documento = serializers.CharField(max_length=30)


class SolicitarRecuperacionClaveSerializer(serializers.Serializer):
    identificador = serializers.CharField(
        max_length=180,
        help_text="Número de documento o correo electrónico registrado.",
    )


class ConfirmarRecuperacionClaveSerializer(serializers.Serializer):
    documento = serializers.CharField(max_length=30)
    token_recuperacion = serializers.CharField(max_length=120)
    nueva_password = serializers.CharField(write_only=True, min_length=8)

    def validate_nueva_password(self, value: str) -> str:
        validate_password(value)
        return value


class CambiarClaveSerializer(serializers.Serializer):
    password_actual = serializers.CharField(write_only=True)
    password_nueva = serializers.CharField(write_only=True, min_length=8)

    def validate_password_nueva(self, value: str) -> str:
        validate_password(value)
        return value


class SuspenderAprendizSerializer(serializers.Serializer):
    motivo_suspension = serializers.CharField(
        min_length=10,
        help_text="Motivo obligatorio (mínimo 10 caracteres) por el cual se suspende/inactiva al aprendiz.",
    )


class CrearInstructorSerializer(serializers.Serializer):
    documento = serializers.CharField(max_length=30)
    nombre_completo = serializers.CharField(max_length=180)
    correo = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_documento(self, value: str) -> str:
        doc = value.strip()
        if Usuario.objects.filter(documento=doc).exists():
            raise serializers.ValidationError("Ya existe un usuario con este documento.")
        return doc

    def validate_correo(self, value: str) -> str:
        email = value.strip().lower()
        if Usuario.objects.filter(correo__iexact=email).exists():
            raise serializers.ValidationError("Ya existe un usuario con este correo electrónico.")
        return email
