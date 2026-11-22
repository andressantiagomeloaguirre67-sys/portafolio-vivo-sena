from rest_framework.permissions import BasePermission
from .models import EstadoCuenta, RolUsuario


class EsInstructorOAdmin(BasePermission):
    """Permite acceso únicamente a Instructores activos o Administradores."""

    message = "Solo los Instructores o Administradores pueden realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.rol in (RolUsuario.INSTRUCTOR, RolUsuario.ADMIN)
        )


class EsAprendizActivo(BasePermission):
    """Permite acceso a Aprendices con cuenta ACTIVA (no suspendida)."""

    message = "Debes ser un Aprendiz con cuenta activa para realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.rol == RolUsuario.APRENDIZ
            and user.estado_cuenta == EstadoCuenta.ACTIVO
        )
