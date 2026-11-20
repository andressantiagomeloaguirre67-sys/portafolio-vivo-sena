"""
Servicios de negocio del Módulo 1: Usuarios (apps/usuarios/services.py)
- Envío de invitación de activación por Gmail SMTP.
- Solicitud y confirmación de recuperación de contraseña.
- Verificación de impacto en Grupo Scrum al suspender un aprendiz.
"""

import secrets
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from .models import EstadoCuenta, RolUsuario, Usuario


def enviar_correo_activacion_aprendiz(
    aprendiz: Usuario,
    ficha_numero: str = "",
    nombre_grupo: str = "",
) -> bool:
    """
    Envía el correo de invitación a Gmail con el enlace y token de activación
    para que el aprendiz cree su contraseña e inicie sesión con su documento.
    """
    if not aprendiz.token_activacion:
        aprendiz.token_activacion = secrets.token_urlsafe(24)
        aprendiz.save(update_fields=["token_activacion"])

    enlace = (
        f"{settings.FRONTEND_URL}/activar-cuenta"
        f"?documento={aprendiz.documento}&token={aprendiz.token_activacion}"
    )
    asunto = f"[Portafolio Vivo SENA ADSO] Activa tu cuenta - Ficha {ficha_numero or 'ADSO'}"
    cuerpo = (
        f"Hola {aprendiz.nombre_completo},\n\n"
        f"Has sido registrado(a) en el Portafolio Vivo SENA ADSO"
        f"{f' en la Ficha {ficha_numero}' if ficha_numero else ''}"
        f"{f' ({nombre_grupo})' if nombre_grupo else ''}.\n\n"
        f"Datos de acceso:\n"
        f"- Usuario (Documento): {aprendiz.documento}\n"
        f"- Token de activación: {aprendiz.token_activacion}\n"
        f"- Enlace de activación: {enlace}\n\n"
        f"Ingresa al enlace para definir tu contraseña y aceptar la política de Habeas Data.\n"
    )
    try:
        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[aprendiz.correo],
            fail_silently=True,
        )
        return True
    except Exception:
        return False


def solicitar_recuperacion_password(identificador: str) -> tuple[Usuario, str]:
    """
    Busca al usuario por su documento o correo electrónico y genera un token temporal
    de recuperación de contraseña válido por 24 horas.
    """
    valor = (identificador or "").strip()
    usuario = Usuario.objects.filter(
        Q(documento=valor) | Q(correo__iexact=valor)
    ).first()

    if not usuario:
        raise ValidationError("No se encontró ningún usuario con ese documento o correo.")

    if usuario.estado_cuenta == EstadoCuenta.SUSPENDIDO:
        raise ValidationError(
            f"La cuenta se encuentra SUSPENDIDA. Motivo: {usuario.motivo_suspension}"
        )

    token = secrets.token_urlsafe(24)
    usuario.token_recuperacion = token
    usuario.fecha_token_recuperacion = timezone.now()
    usuario.save(update_fields=["token_recuperacion", "fecha_token_recuperacion"])

    enlace = (
        f"{settings.FRONTEND_URL}/recuperar-clave"
        f"?documento={usuario.documento}&token={token}"
    )
    send_mail(
        subject="[Portafolio Vivo SENA ADSO] Recuperación de contraseña",
        message=(
            f"Hola {usuario.nombre_completo},\n\n"
            f"Recibimos una solicitud para restablecer la contraseña de tu cuenta "
            f"(Documento: {usuario.documento}).\n\n"
            f"- Token de recuperación: {token}\n"
            f"- Enlace: {enlace}\n\n"
            f"Este enlace es válido por 24 horas."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[usuario.correo],
        fail_silently=True,
    )
    return usuario, token


def confirmar_recuperacion_password(
    documento: str,
    token_recuperacion: str,
    nueva_password: str,
) -> Usuario:
    """
    Valida el token de recuperación y su vigencia (24 horas) y actualiza la contraseña.
    """
    doc_limpio = (documento or "").strip()
    token_limpio = (token_recuperacion or "").strip()

    usuario = Usuario.objects.filter(
        documento=doc_limpio,
        token_recuperacion=token_limpio,
    ).first()

    if not usuario or not token_limpio:
        raise ValidationError("Documento o token de recuperación inválido.")

    if usuario.estado_cuenta == EstadoCuenta.SUSPENDIDO:
        raise ValidationError(
            f"Esta cuenta está SUSPENDIDA. Motivo: {usuario.motivo_suspension}"
        )

    if (
        not usuario.fecha_token_recuperacion
        or timezone.now() - usuario.fecha_token_recuperacion > timedelta(hours=24)
    ):
        raise ValidationError(
            "El token de recuperación ha expirado. Solicita uno nuevo."
        )

    usuario.set_password(nueva_password)
    usuario.token_recuperacion = ""
    usuario.fecha_token_recuperacion = None
    if usuario.estado_cuenta == EstadoCuenta.PENDIENTE:
        usuario.estado_cuenta = EstadoCuenta.ACTIVO
        usuario.is_active = True
        usuario.acepto_habeas_data = True
        usuario.token_activacion = ""
    usuario.save()
    return usuario


def evaluar_alerta_grupo_tras_suspension(aprendiz: Usuario) -> dict | None:
    """
    Regla 3.2: Ningún Grupo Scrum debe tener menos de 2 aprendices activos.
    Verifica si al suspender al aprendiz su Grupo Scrum quedó con menos de 2 integrantes
    no suspendidos, retornando una alerta para el instructor.
    """
    miembro = getattr(aprendiz, "miembro_grupo_scrum", None)
    if not miembro:
        return None

    grupo = miembro.grupo
    miembros_activos = (
        grupo.miembros.filter(activo=True)
        .select_related("aprendiz")
        .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
        .count()
    )
    if miembros_activos < 2:
        return {
            "grupo_id": str(grupo.id),
            "nombre_grupo": grupo.nombre_grupo,
            "aprendices_activos_restantes": miembros_activos,
            "mensaje": (
                f"Atención Instructor: El grupo '{grupo.nombre_grupo}' quedó con "
                f"{miembros_activos} aprendiz(ces) no suspendidos. Recuerda que la regla "
                "SENA exige mínimo 2 aprendices activos por Grupo Scrum; considera "
                "reasignar o disolver el grupo."
            ),
        }
    return None
