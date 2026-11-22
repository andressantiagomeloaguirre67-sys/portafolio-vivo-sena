from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import EstadoCuenta, RolUsuario, Usuario
from .permissions import EsInstructorOAdmin
from .serializers import (
    ActivarCuentaAprendizSerializer,
    CambiarClaveSerializer,
    ConfirmarRecuperacionClaveSerializer,
    CrearInstructorSerializer,
    LoginPorDocumentoSerializer,
    ReenviarActivacionSerializer,
    SolicitarRecuperacionClaveSerializer,
    SuspenderAprendizSerializer,
    UsuarioPerfilSerializer,
)
from .services import (
    confirmar_recuperacion_password,
    enviar_correo_activacion_aprendiz,
    evaluar_alerta_grupo_tras_suspension,
    solicitar_recuperacion_password,
)


class LoginPorDocumentoView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/
    Recibe `documento` y `password` y retorna los tokens JWT + perfil del usuario.
    """

    permission_classes = [AllowAny]
    serializer_class = LoginPorDocumentoSerializer


class PerfilActualView(APIView):
    """
    GET /api/v1/auth/me/
    Retorna el perfil del usuario autenticado junto con su ficha activa y Grupo Scrum.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UsuarioPerfilSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ActivarCuentaAprendizView(APIView):
    """
    POST /api/v1/auth/activar-cuenta/
    Permite al aprendiz invitado por correo Gmail activar su cuenta con su `documento`,
    crear su contraseña, aceptar Habeas Data y recibir sus tokens JWT de acceso.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ActivarCuentaAprendizSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        documento = serializer.validated_data["documento"].strip()
        token = serializer.validated_data["token_activacion"].strip()
        password = serializer.validated_data["password"]

        usuario = Usuario.objects.filter(
            documento=documento,
            token_activacion=token,
        ).first()

        if not usuario or not token:
            return Response(
                {"detalle": "Documento o token de activación inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if usuario.estado_cuenta == EstadoCuenta.SUSPENDIDO:
            return Response(
                {
                    "detalle": (
                        "Esta cuenta fue suspendida por el instructor. "
                        f"Motivo: {usuario.motivo_suspension}"
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        usuario.set_password(password)
        usuario.estado_cuenta = EstadoCuenta.ACTIVO
        usuario.is_active = True
        usuario.acepto_habeas_data = True
        usuario.token_activacion = ""
        usuario.save(
            update_fields=[
                "password",
                "estado_cuenta",
                "is_active",
                "acepto_habeas_data",
                "token_activacion",
            ]
        )

        refresh = RefreshToken.for_user(usuario)
        return Response(
            {
                "mensaje": "Cuenta activada exitosamente. Ya puedes iniciar sesión con tu documento.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "usuario": UsuarioPerfilSerializer(usuario).data,
            },
            status=status.HTTP_200_OK,
        )


class ReenviarActivacionAprendizView(APIView):
    """
    POST /api/v1/auth/reenviar-activacion/
    Reenvía el correo de activación con el enlace y token al aprendiz con cuenta PENDIENTE.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ReenviarActivacionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        documento = serializer.validated_data["documento"].strip()

        aprendiz = Usuario.objects.filter(
            documento=documento, rol=RolUsuario.APRENDIZ
        ).first()
        if not aprendiz:
            return Response(
                {"detalle": "No se encontró un aprendiz con ese documento."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if aprendiz.estado_cuenta == EstadoCuenta.SUSPENDIDO:
            return Response(
                {"detalle": f"La cuenta está SUSPENDIDA. Motivo: {aprendiz.motivo_suspension}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if aprendiz.estado_cuenta == EstadoCuenta.ACTIVO:
            return Response(
                {"detalle": "Esta cuenta ya se encuentra activa. Puedes iniciar sesión con tu documento."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enviar_correo_activacion_aprendiz(aprendiz)
        return Response(
            {
                "mensaje": f"Se ha reenviado el enlace de activación al correo {aprendiz.correo}.",
                "documento": aprendiz.documento,
                "correo": aprendiz.correo,
            },
            status=status.HTTP_200_OK,
        )


class SolicitarRecuperacionClaveView(APIView):
    """
    POST /api/v1/auth/recuperar-clave/solicitar/
    Genera y envía al correo un token de recuperación de contraseña.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SolicitarRecuperacionClaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            usuario, token = solicitar_recuperacion_password(
                serializer.validated_data["identificador"]
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        respuesta = {
            "mensaje": f"Se enviaron las instrucciones de recuperación al correo {usuario.correo}.",
            "documento": usuario.documento,
        }
        # En entorno DEBUG o consola incluimos el token para facilitar pruebas de desarrollo
        from django.conf import settings

        if settings.DEBUG:
            respuesta["token_recuperacion_dev"] = token

        return Response(respuesta, status=status.HTTP_200_OK)


class ConfirmarRecuperacionClaveView(APIView):
    """
    POST /api/v1/auth/recuperar-clave/confirmar/
    Restablece la contraseña usando `documento`, `token_recuperacion` y `nueva_password`.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ConfirmarRecuperacionClaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            usuario = confirmar_recuperacion_password(
                documento=serializer.validated_data["documento"],
                token_recuperacion=serializer.validated_data["token_recuperacion"],
                nueva_password=serializer.validated_data["nueva_password"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "mensaje": "Contraseña actualizada exitosamente. Ya puedes iniciar sesión con tu documento.",
                "usuario": UsuarioPerfilSerializer(usuario).data,
            },
            status=status.HTTP_200_OK,
        )


class CambiarClaveView(APIView):
    """
    POST /api/v1/auth/cambiar-clave/
    Permite al usuario autenticado cambiar su contraseña actual.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CambiarClaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user: Usuario = request.user
        if not user.check_password(serializer.validated_data["password_actual"]):
            return Response(
                {"detalle": "La contraseña actual es incorrecta."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["password_nueva"])
        user.save(update_fields=["password"])
        return Response(
            {"mensaje": "Tu contraseña ha sido actualizada exitosamente."},
            status=status.HTTP_200_OK,
        )


class SuspenderAprendizView(APIView):
    """
    POST /api/v1/auth/aprendices/<uuid:aprendiz_id>/suspender/
    Regla 1 (No Delete): Un aprendiz jamás se borra. El instructor lo suspende con motivo obligatorio.
    Además evalúa si el Grupo Scrum del aprendiz queda con menos de 2 miembros activos (Regla 3.2).
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, aprendiz_id):
        aprendiz = get_object_or_404(
            Usuario, id=aprendiz_id, rol=RolUsuario.APRENDIZ
        )
        serializer = SuspenderAprendizSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        aprendiz.suspender_aprendiz(
            motivo=serializer.validated_data["motivo_suspension"],
            actor=request.user,
        )
        alerta_grupo = evaluar_alerta_grupo_tras_suspension(aprendiz)

        return Response(
            {
                "mensaje": "El aprendiz ha sido suspendido con éxito y su historial permanece intacto.",
                "aprendiz": UsuarioPerfilSerializer(aprendiz).data,
                "alerta_grupo_scrum": alerta_grupo,
            },
            status=status.HTTP_200_OK,
        )


class ReactivarAprendizView(APIView):
    """
    POST /api/v1/auth/aprendices/<uuid:aprendiz_id>/reactivar/
    Permite a un Instructor o Administrador reactivar a un aprendiz suspendido.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, aprendiz_id):
        aprendiz = get_object_or_404(
            Usuario, id=aprendiz_id, rol=RolUsuario.APRENDIZ
        )
        aprendiz.reactivar_aprendiz()
        return Response(
            {
                "mensaje": "El aprendiz ha sido reactivado exitosamente.",
                "aprendiz": UsuarioPerfilSerializer(aprendiz).data,
            },
            status=status.HTTP_200_OK,
        )


class GestionInstructoresView(APIView):
    """
    GET / POST /api/v1/auth/instructores/
    Permite listar instructores o registrar un nuevo instructor activo en la plataforma.
    """

    permission_classes = [EsInstructorOAdmin]

    def get(self, request):
        instructores = Usuario.objects.filter(
            rol=RolUsuario.INSTRUCTOR
        ).order_by("nombre_completo")
        return Response(
            UsuarioPerfilSerializer(instructores, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = CrearInstructorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        instructor = Usuario.objects.create_user(
            documento=datos["documento"],
            nombre_completo=datos["nombre_completo"],
            correo=datos["correo"],
            rol=RolUsuario.INSTRUCTOR,
            password=datos["password"],
            estado_cuenta=EstadoCuenta.ACTIVO,
            is_active=True,
            acepto_habeas_data=True,
        )
        return Response(
            {
                "mensaje": "Instructor registrado y activado exitosamente.",
                "instructor": UsuarioPerfilSerializer(instructor).data,
            },
            status=status.HTTP_201_CREATED,
        )
