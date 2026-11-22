from django.contrib import admin
from .models import RolUsuario, Usuario


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = (
        "documento",
        "nombre_completo",
        "correo",
        "rol",
        "estado_cuenta",
        "is_active",
        "creado_en",
    )
    list_filter = ("rol", "estado_cuenta", "is_active")
    search_fields = ("documento", "nombre_completo", "correo")
    readonly_fields = ("creado_en", "fecha_suspension")

    def has_delete_permission(self, request, obj=None):
        # Prohibido eliminar aprendices también desde el panel Admin
        if obj and obj.rol == RolUsuario.APRENDIZ:
            return False
        return super().has_delete_permission(request, obj=obj)
