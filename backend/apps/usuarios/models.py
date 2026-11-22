"""
Módulo 1: Usuarios (apps/usuarios/models.py)
Regla Inquebrantable 1:
- Inicio de sesión por DOCUMENTO (`documento`).
- PROHIBIDO eliminar aprendices (`No Delete`): jamás se borran de la base de datos.
  Solo se pasan a estado SUSPENDIDO registrando `motivo_suspension` obligatorio.
"""

import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class RolUsuario(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    INSTRUCTOR = "INSTRUCTOR", "Instructor"
    APRENDIZ = "APRENDIZ", "Aprendiz"


class EstadoCuenta(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente de activación"
    ACTIVO = "ACTIVO", "Activo"
    SUSPENDIDO = "SUSPENDIDO", "Suspendido / Inactivo"


class UsuarioQuerySet(models.QuerySet):
    """Impide eliminar aprendices incluso mediante `.delete()` en un QuerySet."""

    def delete(self):
        if self.filter(rol=RolUsuario.APRENDIZ).exists():
            raise ValidationError(
                "Regla SENA Inquebrantable (No Delete): Está prohibido eliminar aprendices "
                "de la base de datos. Debe cambiar su estado a SUSPENDIDO indicando el motivo."
            )
        return super().delete()


class UsuarioManager(BaseUserManager):
    def get_queryset(self):
        return UsuarioQuerySet(self.model, using=self._db)

    def create_user(
        self,
        documento: str,
        nombre_completo: str,
        correo: str,
        rol: str = RolUsuario.APRENDIZ,
        password: str | None = None,
        **extra_fields,
    ):
        if not documento:
            raise ValueError("El número de documento es obligatorio.")
        if not correo:
            raise ValueError("El correo electrónico es obligatorio.")
        if not nombre_completo:
            raise ValueError("El nombre completo es obligatorio.")

        correo = self.normalize_email(correo).lower().strip()
        documento = str(documento).strip()
        nombre_completo = " ".join(str(nombre_completo).strip().split())

        user = self.model(
            documento=documento,
            nombre_completo=nombre_completo,
            correo=correo,
            rol=rol,
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        documento: str,
        nombre_completo: str,
        correo: str,
        rol: str = RolUsuario.ADMIN,
        password: str | None = None,
        **extra_fields,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("estado_cuenta", EstadoCuenta.ACTIVO)
        extra_fields.setdefault("acepto_habeas_data", True)
        return self.create_user(
            documento=documento,
            nombre_completo=nombre_completo,
            correo=correo,
            rol=RolUsuario.ADMIN,
            password=password,
            **extra_fields,
        )


class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    El Aprendiz e Instructor inician sesión con su DOCUMENTO.
    PROHIBIDO eliminar aprendices: solo se pasan a SUSPENDIDO dejando motivo.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    documento = models.CharField(max_length=30, unique=True, db_index=True)
    nombre_completo = models.CharField(max_length=180, db_index=True)
    correo = models.EmailField(unique=True, db_index=True)
    rol = models.CharField(
        max_length=15, choices=RolUsuario.choices, default=RolUsuario.APRENDIZ
    )

    estado_cuenta = models.CharField(
        max_length=15, choices=EstadoCuenta.choices, default=EstadoCuenta.PENDIENTE
    )
    is_active = models.BooleanField(
        default=False
    )  # True cuando activa cuenta y no está suspendido
    is_staff = models.BooleanField(default=False)

    # Auditoría de suspensión (Obligatorio cuando se inactiva/suspende un aprendiz)
    motivo_suspension = models.TextField(blank=True)
    fecha_suspension = models.DateTimeField(null=True, blank=True)
    suspendido_por = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="aprendices_suspendidos",
    )

    # Token de invitación/activación por correo Gmail y recuperación de clave
    token_activacion = models.CharField(max_length=120, blank=True, db_index=True)
    token_recuperacion = models.CharField(max_length=120, blank=True, db_index=True)
    fecha_token_recuperacion = models.DateTimeField(null=True, blank=True)

    acepto_habeas_data = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "documento"
    REQUIRED_FIELDS = ["nombre_completo", "correo", "rol"]

    class Meta:
        db_table = "usuarios"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        ordering = ["nombre_completo"]

    def __str__(self) -> str:
        return f"{self.nombre_completo} ({self.documento}) - {self.rol}"

    def clean(self):
        super().clean()
        if (
            self.estado_cuenta == EstadoCuenta.SUSPENDIDO
            and not (self.motivo_suspension or "").strip()
        ):
            raise ValidationError(
                {
                    "motivo_suspension": (
                        "Es obligatorio registrar el motivo de la suspensión al "
                        "pasar un aprendiz a estado SUSPENDIDO."
                    )
                }
            )

    def delete(self, using=None, keep_parents=False):
        if self.rol == RolUsuario.APRENDIZ:
            raise ValidationError(
                "Regla SENA Inquebrantable (No Delete): Un aprendiz jamás se borra "
                "de la base de datos. Use `suspender_aprendiz(motivo, instructor)`."
            )
        return super().delete(using=using, keep_parents=keep_parents)

    def suspender_aprendiz(self, motivo: str, actor: "Usuario"):
        """
        Suspende al aprendiz dejando constancia de motivo, fecha e instructor responsable.
        Al estar suspendido, no puede iniciar sesión ni aparece en alertas de 'sin proyecto'.
        """
        if self.rol != RolUsuario.APRENDIZ:
            raise ValidationError("Solo las cuentas con rol APRENDIZ usan este flujo de suspensión.")
        motivo_limpio = (motivo or "").strip()
        if len(motivo_limpio) < 10:
            raise ValidationError(
                "Debe especificar un motivo detallado (mínimo 10 caracteres) para suspender al aprendiz."
            )
        self.estado_cuenta = EstadoCuenta.SUSPENDIDO
        self.is_active = False
        self.motivo_suspension = motivo_limpio
        self.fecha_suspension = timezone.now()
        self.suspendido_por = actor
        self.save(
            update_fields=[
                "estado_cuenta",
                "is_active",
                "motivo_suspension",
                "fecha_suspension",
                "suspendido_por",
            ]
        )

    def reactivar_aprendiz(self):
        """
        Reactiva a un aprendiz suspendido.
        Si aún tenía un token de activación pendiente (nunca definió contraseña),
        vuelve a estado PENDIENTE; si ya tenía contraseña definida, pasa a ACTIVO.
        """
        if self.has_usable_password():
            self.estado_cuenta = EstadoCuenta.ACTIVO
            self.is_active = True
        else:
            self.estado_cuenta = EstadoCuenta.PENDIENTE
            self.is_active = False
        self.save(update_fields=["estado_cuenta", "is_active"])

    @property
    def miembro_grupo_scrum(self):
        """
        Retorna la membresía activa del aprendiz en un Grupo Scrum (o None si está sin equipo).
        Mantiene compatibilidad con todos los módulos que consultan el equipo actual del aprendiz.
        """
        if hasattr(self, "_prefetched_objects_cache") and "membresias_grupo_scrum" in self._prefetched_objects_cache:
            for m in self._prefetched_objects_cache["membresias_grupo_scrum"]:
                if m.activo:
                    return m
            return None
        return (
            self.membresias_grupo_scrum.filter(activo=True)
            .select_related("grupo", "grupo__ficha")
            .first()
        )
