"""
Servicios de negocio del Módulo 2 (Fichas, Rotación Trimestral de Instructores y Equipos Scrum).
- Creación directa de Equipos Scrum seleccionando aprendices activos sin equipo de la ficha.
- Garantía transaccional + bloqueo de fila (`select_for_update`) + restricción única parcial en PostgreSQL
  para que un aprendiz nunca pertenezca a más de 1 equipo activo en la misma ficha.
- Regla No-Delete: mover integrantes cierra la membresía previa con `fecha_fin` y abre una nueva;
  archivar un equipo cierra sus membresías activas y libera a los aprendices sin borrar datos.
"""

import secrets
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario
from apps.usuarios.services import enviar_correo_activacion_aprendiz
from .models import (
    AsignacionInstructor,
    Ficha,
    GrupoScrum,
    Matricula,
    MiembroGrupoScrum,
)


@transaction.atomic
def rotar_instructor_ficha(
    ficha: Ficha, nuevo_instructor: Usuario, trimestre: str
) -> AsignacionInstructor:
    """
    Regla 2: Rotación de Instructor por Trimestre.
    - Desactiva al instructor anterior (conservando intacto su historial de asignaciones y comentarios).
    - Deja como único activo al nuevo instructor (`uq_un_solo_instructor_activo_por_ficha`).
    """
    AsignacionInstructor.objects.filter(ficha=ficha, activa=True).update(
        activa=False,
        fecha_fin=timezone.now(),
    )
    asignacion = AsignacionInstructor.objects.create(
        ficha=ficha,
        instructor=nuevo_instructor,
        trimestre=trimestre.strip(),
        activa=True,
    )

    return asignacion


@transaction.atomic
def registrar_e_invitar_aprendiz_individual(
    ficha: Ficha,
    nombre_completo: str,
    documento: str,
    correo: str,
    grupo_scrum: str = "",
) -> tuple[Usuario, bool, bool]:
    """
    Registra (o vincula a la ficha) a un aprendiz individual y le envía el correo
    de invitación/activación con su token por Gmail SMTP cuando su cuenta está PENDIENTE.
    Si se indica `grupo_scrum`, lo asigna a un Grupo Scrum activo existente en la ficha.
    """
    doc_limpio = str(documento or "").strip()
    nombre_limpio = " ".join(str(nombre_completo or "").strip().split())
    correo_limpio = str(correo or "").strip().lower()
    nombre_grupo = " ".join(str(grupo_scrum or "").strip().split())

    if not (doc_limpio and nombre_limpio and correo_limpio):
        raise ValidationError(
            "El nombre completo, el número de documento y el correo electrónico son obligatorios."
        )

    usuario_por_doc = Usuario.objects.filter(documento=doc_limpio).first()
    if usuario_por_doc and usuario_por_doc.rol != RolUsuario.APRENDIZ:
        raise ValidationError(
            f"El documento '{doc_limpio}' ya pertenece a una cuenta con rol {usuario_por_doc.rol}."
        )

    usuario_por_correo = Usuario.objects.filter(correo__iexact=correo_limpio).first()
    if usuario_por_correo and usuario_por_correo.documento != doc_limpio:
        raise ValidationError(
            f"El correo '{correo_limpio}' ya está registrado con otro documento ({usuario_por_correo.documento})."
        )

    grupo_obj = None
    if nombre_grupo:
        grupo_obj = (
            GrupoScrum.objects.filter(ficha=ficha, nombre_grupo__iexact=nombre_grupo)
            .exclude(estado=GrupoScrum.EstadoGrupo.ARCHIVADO)
            .first()
        )
        if not grupo_obj:
            raise ValidationError(
                f"El equipo '{nombre_grupo}' no existe o está archivado en la ficha {ficha.numero}."
            )

    if usuario_por_doc:
        aprendiz = usuario_por_doc
        creado = False
        if aprendiz.estado_cuenta == EstadoCuenta.SUSPENDIDO:
            raise ValidationError(
                f"El aprendiz {aprendiz.nombre_completo} ({aprendiz.documento}) está SUSPENDIDO. "
                "Debes reactivarlo desde la sección Aprendices (Regla No-Delete)."
            )
    else:
        aprendiz = Usuario.objects.create(
            documento=doc_limpio,
            nombre_completo=nombre_limpio,
            correo=correo_limpio,
            rol=RolUsuario.APRENDIZ,
            estado_cuenta=EstadoCuenta.PENDIENTE,
            is_active=False,
            token_activacion=secrets.token_urlsafe(24),
        )
        aprendiz.set_unusable_password()
        aprendiz.save(update_fields=["password"])
        creado = True

    # Matricular en la ficha activa (1 matrícula activa por aprendiz)
    Matricula.objects.filter(aprendiz=aprendiz, activa=True).exclude(
        ficha=ficha
    ).update(activa=False)
    Matricula.objects.update_or_create(
        aprendiz=aprendiz,
        ficha=ficha,
        defaults={"activa": True},
    )

    if grupo_obj:
        agregar_integrante_a_equipo(
            grupo=grupo_obj,
            aprendiz_id=aprendiz.id,
            rol_scrum=MiembroGrupoScrum.RolScrum.DEVELOPER,
        )

    correo_enviado = False
    if aprendiz.estado_cuenta == EstadoCuenta.PENDIENTE:
        correo_enviado = enviar_correo_activacion_aprendiz(
            aprendiz=aprendiz,
            ficha_numero=ficha.numero,
            nombre_grupo=grupo_obj.nombre_grupo if grupo_obj else "",
        )

    return aprendiz, creado, correo_enviado


def _validar_roles_scrum_lista(integrantes_normalizados: list[tuple[Usuario, str]]):
    sm = [u for u, rol in integrantes_normalizados if rol == MiembroGrupoScrum.RolScrum.SCRUM_MASTER]
    po = [u for u, rol in integrantes_normalizados if rol == MiembroGrupoScrum.RolScrum.PRODUCT_OWNER]
    if len(sm) > 1:
        raise ValidationError("Solo puede haber un Scrum Master por equipo.")
    if len(po) > 1:
        raise ValidationError("Solo puede haber un Product Owner por equipo.")


@transaction.atomic
def crear_equipo_scrum(
    ficha: Ficha,
    nombre_grupo: str,
    proyecto_titulo: str,
    proyecto_descripcion: str,
    integrantes: list[dict],
    estado: str = GrupoScrum.EstadoGrupo.BORRADOR,
) -> GrupoScrum:
    """
    Crea un Equipo Scrum junto con su proyecto asociado y asigna sus integrantes activos
    dentro de una sola transacción con bloqueo de fila (`select_for_update`) sobre los
    aprendices involucrados para prevenir condiciones de carrera.
    """
    from apps.proyectos.models import Proyecto

    nombre_limpio = " ".join(str(nombre_grupo or "").strip().split())
    titulo_limpio = " ".join(str(proyecto_titulo or "").strip().split())
    desc_limpia = str(proyecto_descripcion or "").strip()
    estado_limpio = (estado or GrupoScrum.EstadoGrupo.BORRADOR).strip().upper()

    if not nombre_limpio:
        raise ValidationError("El nombre del equipo es obligatorio.")
    if not titulo_limpio:
        raise ValidationError("El nombre del proyecto es obligatorio.")
    if len(desc_limpia) < 10:
        raise ValidationError("La descripción corta del proyecto debe tener al menos 10 caracteres.")
    if estado_limpio not in (
        GrupoScrum.EstadoGrupo.BORRADOR,
        GrupoScrum.EstadoGrupo.PUBLICADO,
    ):
        raise ValidationError("El estado inicial debe ser BORRADOR o PUBLICADO.")

    # Verificar nombre único dentro de la ficha (entre equipos no archivados)
    if (
        GrupoScrum.objects.filter(ficha=ficha, nombre_grupo__iexact=nombre_limpio)
        .exclude(estado=GrupoScrum.EstadoGrupo.ARCHIVADO)
        .exists()
    ):
        raise ValidationError(
            f"Ya existe un equipo llamado '{nombre_limpio}' en la ficha {ficha.numero}."
        )

    if Proyecto.objects.filter(titulo__iexact=titulo_limpio).exists():
        raise ValidationError(
            f"Ya existe un proyecto registrado con el título '{titulo_limpio}'. Usa un título único."
        )

    # Normalizar y deduplicar integrantes solicitados
    roles_por_id: dict[str, str] = {}
    roles_validos = {c[0] for c in MiembroGrupoScrum.RolScrum.choices}
    for item in integrantes or []:
        apr_id = str(item.get("aprendiz_id") or "").strip()
        if not apr_id:
            continue
        rol = str(item.get("rol_scrum") or MiembroGrupoScrum.RolScrum.DEVELOPER).strip().upper()
        if rol not in roles_validos:
            raise ValidationError(f"Rol Scrum inválido: {rol}.")
        roles_por_id[apr_id] = rol

    if len(roles_por_id) < 2:
        raise ValidationError(
            "Regla SENA: Todo equipo Scrum debe tener mínimo 2 aprendices activos."
        )

    # Bloquear filas de aprendices en orden determinista para evitar deadlocks y condiciones de carrera
    ids_ordenados = sorted(roles_por_id.keys())
    aprendices_bloqueados = list(
        Usuario.objects.select_for_update()
        .filter(id__in=ids_ordenados, rol=RolUsuario.APRENDIZ)
        .order_by("id")
    )
    if len(aprendices_bloqueados) != len(ids_ordenados):
        raise ValidationError("Uno o más aprendices seleccionados no existen.")

    integrantes_norm: list[tuple[Usuario, str]] = []
    for apr in aprendices_bloqueados:
        if apr.estado_cuenta == EstadoCuenta.SUSPENDIDO:
            raise ValidationError(
                f"El aprendiz {apr.nombre_completo} está suspendido y no puede integrarse a un equipo."
            )
        if not Matricula.objects.filter(aprendiz=apr, ficha=ficha, activa=True).exists():
            raise ValidationError(
                f"El aprendiz {apr.nombre_completo} no pertenece a la ficha {ficha.numero}."
            )
        membresia_activa = (
            MiembroGrupoScrum.objects.select_related("grupo")
            .filter(ficha=ficha, aprendiz=apr, activo=True)
            .first()
        )
        if membresia_activa:
            raise ValidationError(
                f"Este aprendiz ({apr.nombre_completo}) ya fue asignado al {membresia_activa.grupo.nombre_grupo}."
            )
        integrantes_norm.append((apr, roles_por_id[str(apr.id)]))

    _validar_roles_scrum_lista(integrantes_norm)

    try:
        from apps.asistente.services import (
            adquirir_bloqueo_originalidad,
            evaluar_originalidad_idea,
        )

        adquirir_bloqueo_originalidad()

        grupo = GrupoScrum.objects.create(
            ficha=ficha,
            nombre_grupo=nombre_limpio,
            estado=estado_limpio,
        )

        evaluacion_orig = evaluar_originalidad_idea(
            titulo_propuesto=titulo_limpio,
            idea_propuesta=desc_limpia,
            excluir_grupo_id=grupo.id,
        )
        es_original = evaluacion_orig["veredicto"] == "ORIGINAL"

        estado_proyecto = (
            Proyecto.EstadoProyecto.PUBLICADO
            if estado_limpio == GrupoScrum.EstadoGrupo.PUBLICADO
            else Proyecto.EstadoProyecto.DEFINIENDO_IDEA
        )
        visibilidad_proyecto = (
            Proyecto.Visibilidad.PUBLICO
            if estado_limpio == GrupoScrum.EstadoGrupo.PUBLICADO
            else Proyecto.Visibilidad.FICHA
        )
        Proyecto.objects.create(
            ficha=ficha,
            grupo_scrum=grupo,
            titulo=titulo_limpio,
            introduccion=desc_limpia,
            embedding_idea=evaluacion_orig["embedding"] if es_original else None,
            estado_originalidad=(
                Proyecto.EstadoOriginalidad.ORIGINAL
                if es_original
                else Proyecto.EstadoOriginalidad.EN_DIFERENCIACION
            ),
            estado=estado_proyecto,
            visibilidad=visibilidad_proyecto,
        )

        for apr, rol in integrantes_norm:
            MiembroGrupoScrum.objects.create(
                ficha=ficha,
                grupo=grupo,
                aprendiz=apr,
                rol_scrum=rol,
                activo=True,
            )
    except IntegrityError as exc:
        # Respaldo de segunda línea si PostgreSQL dispara la restricción única parcial
        detalle_str = str(exc)
        if "uq_un_grupo_activo_por_ficha_y_aprendiz" in detalle_str:
            raise ValidationError(
                "Uno de los aprendices ya fue asignado a otro equipo en esta ficha de forma simultánea."
            )
        if "uq_nombre_grupo_activo_por_ficha" in detalle_str:
            raise ValidationError(
                f"Ya existe un equipo llamado '{nombre_limpio}' en esta ficha."
            )
        raise ValidationError("No se pudo crear el equipo por un conflicto de unicidad en base de datos.")

    return grupo


@transaction.atomic
def agregar_integrante_a_equipo(
    grupo: GrupoScrum,
    aprendiz_id,
    rol_scrum: str = MiembroGrupoScrum.RolScrum.DEVELOPER,
) -> MiembroGrupoScrum:
    """
    Agrega un aprendiz activo sin equipo de la misma ficha a `grupo`,
    con bloqueo transaccional sobre el aprendiz y el equipo.
    """
    grupo = GrupoScrum.objects.select_for_update().select_related("ficha").get(id=grupo.id)
    if grupo.estado == GrupoScrum.EstadoGrupo.ARCHIVADO:
        raise ValidationError("No se pueden agregar integrantes a un equipo archivado.")

    rol = (rol_scrum or MiembroGrupoScrum.RolScrum.DEVELOPER).strip().upper()
    if rol not in {c[0] for c in MiembroGrupoScrum.RolScrum.choices}:
        raise ValidationError(f"Rol Scrum inválido: {rol}.")

    aprendiz = (
        Usuario.objects.select_for_update()
        .filter(id=aprendiz_id, rol=RolUsuario.APRENDIZ)
        .first()
    )
    if not aprendiz:
        raise ValidationError("No se encontró el aprendiz seleccionado.")
    if aprendiz.estado_cuenta == EstadoCuenta.SUSPENDIDO:
        raise ValidationError(
            f"El aprendiz {aprendiz.nombre_completo} está suspendido y no puede asignarse a un equipo."
        )
    if not Matricula.objects.filter(aprendiz=aprendiz, ficha=grupo.ficha, activa=True).exists():
        raise ValidationError(
            f"El aprendiz {aprendiz.nombre_completo} no tiene matrícula activa en la ficha {grupo.ficha.numero}."
        )

    membresia_existente = (
        MiembroGrupoScrum.objects.select_related("grupo")
        .filter(ficha=grupo.ficha, aprendiz=aprendiz, activo=True)
        .first()
    )
    if membresia_existente:
        raise ValidationError(
            f"Este aprendiz ya fue asignado al {membresia_existente.grupo.nombre_grupo}."
        )

    if rol in (
        MiembroGrupoScrum.RolScrum.SCRUM_MASTER,
        MiembroGrupoScrum.RolScrum.PRODUCT_OWNER,
    ):
        ocupado = MiembroGrupoScrum.objects.filter(
            grupo=grupo, activo=True, rol_scrum=rol
        ).exists()
        if ocupado:
            etiqueta = "Scrum Master" if rol == MiembroGrupoScrum.RolScrum.SCRUM_MASTER else "Product Owner"
            raise ValidationError(f"El equipo '{grupo.nombre_grupo}' ya tiene un {etiqueta} asignado.")

    try:
        return MiembroGrupoScrum.objects.create(
            ficha=grupo.ficha,
            grupo=grupo,
            aprendiz=aprendiz,
            rol_scrum=rol,
            activo=True,
        )
    except IntegrityError:
        membresia = (
            MiembroGrupoScrum.objects.select_related("grupo")
            .filter(ficha=grupo.ficha, aprendiz=aprendiz, activo=True)
            .first()
        )
        if membresia:
            raise ValidationError(
                f"Este aprendiz ya fue asignado al {membresia.grupo.nombre_grupo}."
            )
        raise ValidationError("Conflicto de unicidad al asignar el integrante al equipo.")


@transaction.atomic
def mover_integrante_de_equipo(
    grupo_origen: GrupoScrum,
    aprendiz_id,
    grupo_destino_id,
    rol_scrum: str = MiembroGrupoScrum.RolScrum.DEVELOPER,
) -> MiembroGrupoScrum:
    """
    Mueve un aprendiz desde `grupo_origen` hacia `grupo_destino` dentro de la misma ficha:
    - Cierra la membresía anterior (`activo=False`, `fecha_fin=now`, sin borrar).
    - Abre una nueva membresía activa en el equipo destino (nunca dos activas a la vez).
    - Bloquea la operación si `grupo_origen` quedaría con menos de 2 integrantes activos.
    """
    if str(grupo_origen.id) == str(grupo_destino_id):
        raise ValidationError("El equipo destino debe ser diferente al equipo actual.")

    ids_grupos = sorted([str(grupo_origen.id), str(grupo_destino_id)])
    grupos_bloqueados = {
        str(g.id): g
        for g in GrupoScrum.objects.select_for_update()
        .select_related("ficha")
        .filter(id__in=ids_grupos)
        .order_by("id")
    }
    origen = grupos_bloqueados.get(str(grupo_origen.id))
    destino = grupos_bloqueados.get(str(grupo_destino_id))
    if not origen or not destino:
        raise ValidationError("No se encontró el equipo origen o el equipo destino.")
    if origen.ficha_id != destino.ficha_id:
        raise ValidationError("Solo puedes mover aprendices entre equipos de la misma ficha.")
    if origen.estado == GrupoScrum.EstadoGrupo.ARCHIVADO:
        raise ValidationError("No puedes mover integrantes desde un equipo archivado.")
    if destino.estado == GrupoScrum.EstadoGrupo.ARCHIVADO:
        raise ValidationError("No puedes mover integrantes hacia un equipo archivado.")

    aprendiz = (
        Usuario.objects.select_for_update()
        .filter(id=aprendiz_id, rol=RolUsuario.APRENDIZ)
        .first()
    )
    if not aprendiz:
        raise ValidationError("No se encontró el aprendiz especificado.")

    membresia_actual = MiembroGrupoScrum.objects.filter(
        grupo=origen, aprendiz=aprendiz, activo=True
    ).first()
    if not membresia_actual:
        raise ValidationError(
            f"{aprendiz.nombre_completo} no tiene una membresía activa en '{origen.nombre_grupo}'."
        )

    activos_origen = (
        MiembroGrupoScrum.objects.filter(grupo=origen, activo=True)
        .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
        .count()
    )
    if activos_origen - 1 < 2:
        raise ValidationError(
            f"No se puede mover a {aprendiz.nombre_completo}: '{origen.nombre_grupo}' quedaría con "
            f"{activos_origen - 1} integrante(s) activo(s) y el mínimo SENA es 2."
        )

    rol = (rol_scrum or MiembroGrupoScrum.RolScrum.DEVELOPER).strip().upper()
    if rol not in {c[0] for c in MiembroGrupoScrum.RolScrum.choices}:
        raise ValidationError(f"Rol Scrum inválido: {rol}.")
    if rol in (
        MiembroGrupoScrum.RolScrum.SCRUM_MASTER,
        MiembroGrupoScrum.RolScrum.PRODUCT_OWNER,
    ):
        if MiembroGrupoScrum.objects.filter(grupo=destino, activo=True, rol_scrum=rol).exists():
            etiqueta = "Scrum Master" if rol == MiembroGrupoScrum.RolScrum.SCRUM_MASTER else "Product Owner"
            raise ValidationError(
                f"El equipo '{destino.nombre_grupo}' ya tiene un {etiqueta} asignado."
            )

    ahora = timezone.now()
    membresia_actual.activo = False
    membresia_actual.fecha_fin = ahora
    membresia_actual.save(update_fields=["activo", "fecha_fin"])

    return MiembroGrupoScrum.objects.create(
        ficha=destino.ficha,
        grupo=destino,
        aprendiz=aprendiz,
        rol_scrum=rol,
        activo=True,
    )


@transaction.atomic
def cambiar_rol_integrante_equipo(
    grupo: GrupoScrum,
    aprendiz_id,
    rol_scrum: str,
) -> MiembroGrupoScrum:
    """Actualiza el rol Scrum de un integrante activo garantizando un solo SM y un solo PO."""
    grupo = GrupoScrum.objects.select_for_update().get(id=grupo.id)
    if grupo.estado == GrupoScrum.EstadoGrupo.ARCHIVADO:
        raise ValidationError("No se pueden editar roles en un equipo archivado.")

    rol = (rol_scrum or "").strip().upper()
    if rol not in {c[0] for c in MiembroGrupoScrum.RolScrum.choices}:
        raise ValidationError(f"Rol Scrum inválido: {rol}.")

    membresia = MiembroGrupoScrum.objects.filter(
        grupo=grupo, aprendiz_id=aprendiz_id, activo=True
    ).first()
    if not membresia:
        raise ValidationError("El aprendiz no pertenece activamente a este equipo.")

    if rol in (
        MiembroGrupoScrum.RolScrum.SCRUM_MASTER,
        MiembroGrupoScrum.RolScrum.PRODUCT_OWNER,
    ):
        ocupado = (
            MiembroGrupoScrum.objects.filter(grupo=grupo, activo=True, rol_scrum=rol)
            .exclude(id=membresia.id)
            .exists()
        )
        if ocupado:
            etiqueta = "Scrum Master" if rol == MiembroGrupoScrum.RolScrum.SCRUM_MASTER else "Product Owner"
            raise ValidationError(f"Este equipo ya tiene otro integrante como {etiqueta}.")

    membresia.rol_scrum = rol
    membresia.save(update_fields=["rol_scrum"])
    return membresia


@transaction.atomic
def cambiar_estado_equipo_scrum(grupo: GrupoScrum, nuevo_estado: str) -> GrupoScrum:
    """Alterna el estado de un equipo entre BORRADOR y PUBLICADO y sincroniza su proyecto."""
    from apps.proyectos.models import Proyecto

    grupo = GrupoScrum.objects.select_for_update().get(id=grupo.id)
    if grupo.estado == GrupoScrum.EstadoGrupo.ARCHIVADO:
        raise ValidationError("Un equipo archivado no puede volver a publicarse directamente.")

    estado_limpio = (nuevo_estado or "").strip().upper()
    if estado_limpio not in (
        GrupoScrum.EstadoGrupo.BORRADOR,
        GrupoScrum.EstadoGrupo.PUBLICADO,
    ):
        raise ValidationError("Solo puedes cambiar el estado a BORRADOR o PUBLICADO.")

    if estado_limpio == GrupoScrum.EstadoGrupo.PUBLICADO:
        activos = (
            MiembroGrupoScrum.objects.filter(grupo=grupo, activo=True)
            .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
            .count()
        )
        if activos < 2:
            raise ValidationError(
                "No se puede publicar el equipo porque tiene menos de 2 integrantes activos."
            )

    grupo.estado = estado_limpio
    grupo.save(update_fields=["estado"])

    proyecto = getattr(grupo, "proyecto", None)
    if proyecto:
        if estado_limpio == GrupoScrum.EstadoGrupo.PUBLICADO:
            proyecto.estado = Proyecto.EstadoProyecto.PUBLICADO
            proyecto.visibilidad = Proyecto.Visibilidad.PUBLICO
        else:
            proyecto.estado = Proyecto.EstadoProyecto.DEFINIENDO_IDEA
            proyecto.visibilidad = Proyecto.Visibilidad.FICHA
        proyecto.save(update_fields=["estado", "visibilidad"])

    return grupo


@transaction.atomic
def archivar_equipo_scrum(grupo: GrupoScrum) -> dict:
    """
    Regla No-Delete: archiva el equipo en lugar de eliminarlo físicamente.
    - Marca `grupo.estado = ARCHIVADO` y `archivado_en = now`.
    - Cierra todas las membresías activas (`activo = False`, `fecha_fin = now`),
      liberando a los aprendices para que puedan integrarse a otro equipo de la ficha.
    - Marca el proyecto asociado como retirado por instructor sin borrar el registro ni su bitácora.
    """
    from apps.proyectos.models import Proyecto

    grupo = GrupoScrum.objects.select_for_update().select_related("ficha").get(id=grupo.id)
    if grupo.estado == GrupoScrum.EstadoGrupo.ARCHIVADO:
        raise ValidationError("Este equipo ya se encuentra archivado.")

    ahora = timezone.now()
    membresias_activas = list(
        MiembroGrupoScrum.objects.select_related("aprendiz").filter(
            grupo=grupo, activo=True
        )
    )
    aprendices_liberados = [
        {
            "id": str(m.aprendiz.id),
            "documento": m.aprendiz.documento,
            "nombre_completo": m.aprendiz.nombre_completo,
        }
        for m in membresias_activas
    ]

    MiembroGrupoScrum.objects.filter(grupo=grupo, activo=True).update(
        activo=False, fecha_fin=ahora
    )

    grupo.estado = GrupoScrum.EstadoGrupo.ARCHIVADO
    grupo.archivado_en = ahora
    grupo.save(update_fields=["estado", "archivado_en"])

    proyecto = getattr(grupo, "proyecto", None)
    if proyecto:
        proyecto.estado = Proyecto.EstadoProyecto.RETIRADO_INSTRUCTOR
        proyecto.save(update_fields=["estado"])

    return {
        "grupo_id": str(grupo.id),
        "nombre_grupo": grupo.nombre_grupo,
        "ficha_numero": grupo.ficha.numero,
        "aprendices_liberados": aprendices_liberados,
    }
