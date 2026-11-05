"""
Servicios de negocio del Módulo 2 (Fichas, Rotación Trimestral de Instructores y Grupos Scrum).
Incluye lector de archivos Excel (.xlsx) y CSV (.csv) con detección exhaustiva de duplicados,
rotación trimestral con reasignación de consultas pendientes y gestión de Grupos Scrum.
"""

import csv
import io
import secrets
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario
from apps.usuarios.services import enviar_correo_activacion_aprendiz
from .models import (
    AsignacionInstructor,
    CargaMasiva,
    Ficha,
    GrupoScrum,
    Matricula,
    MiembroGrupoScrum,
)


def normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre completo quitando tildes y espacios múltiples para detectar duplicados."""
    texto = " ".join(str(nombre or "").strip().upper().split())
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def extraer_registros_desde_archivo(archivo_subido) -> list[dict]:
    """
    Lee un archivo .csv o .xlsx subido por el instructor y extrae las filas
    esperadas: `nombre_completo`, `documento`, `correo`, `grupo_scrum`.
    """
    nombre = (getattr(archivo_subido, "name", "") or "").lower()
    contenido = archivo_subido.read()

    if nombre.endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
        ws = wb.active
        filas = list(ws.iter_rows(values_only=True))
        if not filas:
            return []
        encabezados = [
            normalizar_nombre(str(col or "")).lower().replace(" ", "_")
            for col in filas[0]
        ]
        registros = []
        for fila in filas[1:]:
            if not any(fila):
                continue
            item = dict(zip(encabezados, [str(v or "").strip() for v in fila]))
            registros.append(
                {
                    "nombre_completo": item.get("nombre_completo")
                    or item.get("nombre")
                    or item.get("aprendiz")
                    or "",
                    "documento": item.get("documento")
                    or item.get("numero_documento")
                    or item.get("identificacion")
                    or "",
                    "correo": item.get("correo")
                    or item.get("email")
                    or item.get("correo_electronico")
                    or "",
                    "grupo_scrum": item.get("grupo_scrum")
                    or item.get("grupo")
                    or item.get("equipo_scrum")
                    or "",
                }
            )
        return registros

    # Por defecto procesa como CSV (UTF-8 / Latin-1)
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")

    # Soportar delimitador coma (,) o punto y coma (;) típico de Excel en español
    primera_linea = texto.splitlines()[0] if texto.splitlines() else ""
    delimitador = ";" if primera_linea.count(";") > primera_linea.count(",") else ","

    lector = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
    registros = []
    for fila in lector:
        fila_norm = {
            normalizar_nombre(k).lower().replace(" ", "_"): str(v or "").strip()
            for k, v in fila.items()
            if k
        }
        if not any(fila_norm.values()):
            continue
        registros.append(
            {
                "nombre_completo": fila_norm.get("nombre_completo")
                or fila_norm.get("nombre")
                or fila_norm.get("aprendiz")
                or "",
                "documento": fila_norm.get("documento")
                or fila_norm.get("numero_documento")
                or fila_norm.get("identificacion")
                or "",
                "correo": fila_norm.get("correo")
                or fila_norm.get("email")
                or fila_norm.get("correo_electronico")
                or "",
                "grupo_scrum": fila_norm.get("grupo_scrum")
                or fila_norm.get("grupo")
                or fila_norm.get("equipo_scrum")
                or "",
            }
        )
    return registros


@transaction.atomic
def rotar_instructor_ficha(
    ficha: Ficha, nuevo_instructor: Usuario, trimestre: str
) -> AsignacionInstructor:
    """
    Regla 2: Rotación de Instructor por Trimestre.
    - Desactiva al instructor anterior (conservando intacto su historial de asignaciones y comentarios).
    - Deja como único activo al nuevo instructor (`uq_un_solo_instructor_activo_por_ficha`).
    - Reasigna automáticamente cualquier consulta escalada por el Agente IA que aún esté PENDIENTE
      en esa ficha al nuevo instructor activo del trimestre.
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

    # Reasignar consultas técnicas PENDIENTES de los proyectos de la ficha al nuevo instructor activo
    from apps.revisiones.models import ConsultaEscaladaInstructor

    ConsultaEscaladaInstructor.objects.filter(
        proyecto__ficha=ficha,
        estado=ConsultaEscaladaInstructor.EstadoConsulta.PENDIENTE,
    ).update(instructor_destino=nuevo_instructor)

    return asignacion


def validar_registros_carga_masiva(registros: list[dict]) -> list[dict]:
    """
    Regla 3:
    - Ningún aprendiz puede estar en más de un Grupo Scrum (verifica `documento` y `nombre_completo`).
    - Ningún nombre completo o correo puede estar duplicado con distinto documento.
    - Mínimo 2 aprendices por Grupo Scrum.
    - Verifica conflictos contra la base de datos (ej. correo registrado en otro documento).
    Retorna la lista de alertas encontradas. Si está vacía, el archivo es válido.
    """
    alertas = []
    grupos_por_documento: dict[str, set[str]] = defaultdict(set)
    grupos_por_nombre: dict[str, set[str]] = defaultdict(set)
    documentos_por_nombre: dict[str, set[str]] = defaultdict(set)
    documentos_por_correo: dict[str, set[str]] = defaultdict(set)
    miembros_por_grupo: dict[str, set[str]] = defaultdict(set)

    documentos_archivo: set[str] = set()
    correos_archivo: dict[str, str] = {}

    for idx, fila in enumerate(registros, start=1):
        documento = str(fila.get("documento", "")).strip()
        nombre_completo = str(fila.get("nombre_completo", "")).strip()
        correo = str(fila.get("correo", "")).strip().lower()
        grupo_scrum = " ".join(str(fila.get("grupo_scrum", "")).strip().split())

        if not (documento and nombre_completo and correo and grupo_scrum):
            alertas.append(
                {
                    "tipo": "FILA_INCOMPLETA",
                    "fila": idx,
                    "mensaje": (
                        f"La fila {idx} no contiene todos los campos obligatorios "
                        "(nombre_completo, documento, correo, grupo_scrum)."
                    ),
                }
            )
            continue

        nombre_norm = normalizar_nombre(nombre_completo)
        grupos_por_documento[documento].add(grupo_scrum)
        grupos_por_nombre[nombre_norm].add(grupo_scrum)
        documentos_por_nombre[nombre_norm].add(documento)
        documentos_por_correo[correo].add(documento)
        miembros_por_grupo[grupo_scrum].add(documento)

        documentos_archivo.add(documento)
        correos_archivo[correo] = documento

    # 1. Detectar aprendices repetidos en varios grupos por documento
    for doc, grupos in grupos_por_documento.items():
        if len(grupos) > 1:
            alertas.append(
                {
                    "tipo": "DOCUMENTO_EN_VARIOS_GRUPOS",
                    "documento": doc,
                    "grupos": sorted(grupos),
                    "mensaje": (
                        f"El documento '{doc}' aparece asignado en múltiples Grupos Scrum: "
                        f"{', '.join(sorted(grupos))}."
                    ),
                }
            )

    # 2. Detectar aprendices repetidos en varios grupos por nombre_completo
    for nombre_norm, grupos in grupos_por_nombre.items():
        if len(grupos) > 1:
            alertas.append(
                {
                    "tipo": "NOMBRE_EN_VARIOS_GRUPOS",
                    "nombre_completo": nombre_norm,
                    "grupos": sorted(grupos),
                    "mensaje": (
                        f"La persona '{nombre_norm}' aparece repetida en varios Grupos Scrum: "
                        f"{', '.join(sorted(grupos))}."
                    ),
                }
            )

    # 3. Detectar mismo nombre_completo con diferentes números de documento
    for nombre_norm, docs in documentos_por_nombre.items():
        if len(docs) > 1 and len(grupos_por_nombre[nombre_norm]) == 1:
            alertas.append(
                {
                    "tipo": "NOMBRE_CON_MULTIPLES_DOCUMENTOS",
                    "nombre_completo": nombre_norm,
                    "documentos": sorted(docs),
                    "mensaje": (
                        f"La persona '{nombre_norm}' aparece registrada con múltiples documentos "
                        f"distintos: {', '.join(sorted(docs))}."
                    ),
                }
            )

    # 4. Detectar mismo correo asignado a múltiples documentos en el archivo
    for correo, docs in documentos_por_correo.items():
        if len(docs) > 1:
            alertas.append(
                {
                    "tipo": "CORREO_REPETIDO_EN_ARCHIVO",
                    "correo": correo,
                    "documentos": sorted(docs),
                    "mensaje": (
                        f"El correo '{correo}' está asignado a múltiples documentos en el archivo: "
                        f"{', '.join(sorted(docs))}."
                    ),
                }
            )

    # 5. Validar mínimo 2 aprendices por Grupo Scrum
    for nombre_grupo, docs in miembros_por_grupo.items():
        if len(docs) < 2:
            alertas.append(
                {
                    "tipo": "GRUPO_MENOR_A_DOS_APRENDICES",
                    "grupo_scrum": nombre_grupo,
                    "cantidad_aprendices": len(docs),
                    "mensaje": (
                        f"El grupo '{nombre_grupo}' tiene {len(docs)} aprendiz(ces). "
                        "Regla SENA: mínimo 2 aprendices por Grupo Scrum."
                    ),
                }
            )

    # 6. Verificar conflictos de integridad con usuarios ya existentes en PostgreSQL
    if documentos_archivo:
        usuarios_no_aprendices = Usuario.objects.filter(
            documento__in=documentos_archivo
        ).exclude(rol=RolUsuario.APRENDIZ)
        for u in usuarios_no_aprendices:
            alertas.append(
                {
                    "tipo": "DOCUMENTO_PERTENECE_A_INSTRUCTOR_O_ADMIN",
                    "documento": u.documento,
                    "rol_actual": u.rol,
                    "mensaje": (
                        f"El documento '{u.documento}' pertenece a una cuenta con rol {u.rol} "
                        "y no puede cargarse como aprendiz."
                    ),
                }
            )

    if correos_archivo:
        usuarios_con_correo = Usuario.objects.filter(
            correo__in=list(correos_archivo.keys())
        )
        for u in usuarios_con_correo:
            doc_esperado = correos_archivo.get(u.correo.lower())
            if doc_esperado and u.documento != doc_esperado:
                alertas.append(
                    {
                        "tipo": "CORREO_YA_REGISTRADO_OTRO_DOCUMENTO",
                        "correo": u.correo,
                        "documento_archivo": doc_esperado,
                        "documento_existente": u.documento,
                        "mensaje": (
                            f"El correo '{u.correo}' ya pertenece a otro usuario registrado "
                            f"con el documento '{u.documento}'."
                        ),
                    }
                )

    return alertas


@transaction.atomic
def procesar_carga_masiva_ficha(
    ficha: Ficha,
    instructor: Usuario,
    registros: list[dict],
    nombre_archivo: str = "carga_manual.json",
) -> tuple[CargaMasiva, list[dict]]:
    """
    Valida y procesa la creación de Aprendices, Matrículas y Grupos Scrum para una Ficha.
    Si detecta alertas de duplicados o grupos < 2 miembros, registra la alerta inmediata
    sin aplicar cambios parciales.
    Envía invitación por correo Gmail a los aprendices con cuenta PENDIENTE.
    """
    alertas = validar_registros_carga_masiva(registros)
    if alertas:
        carga = CargaMasiva.objects.create(
            instructor=instructor,
            ficha=ficha,
            archivo=nombre_archivo,
            estado="CON_ALERTAS",
            alertas_duplicados=alertas,
        )
        return carga, alertas

    aprendices_creados_o_vinculados = []
    documentos_procesados: set[str] = set()

    for fila in registros:
        documento = str(fila["documento"]).strip()
        if documento in documentos_procesados:
            continue
        documentos_procesados.add(documento)

        nombre_completo = " ".join(str(fila["nombre_completo"]).strip().split())
        correo = str(fila["correo"]).strip().lower()
        nombre_grupo = " ".join(str(fila["grupo_scrum"]).strip().split())

        aprendiz, creado = Usuario.objects.get_or_create(
            documento=documento,
            defaults={
                "nombre_completo": nombre_completo,
                "correo": correo,
                "rol": RolUsuario.APRENDIZ,
                "estado_cuenta": EstadoCuenta.PENDIENTE,
                "is_active": False,
                "token_activacion": secrets.token_urlsafe(24),
            },
        )
        if creado:
            aprendiz.set_unusable_password()
            aprendiz.save(update_fields=["password"])

        # Enviar correo de invitación por Gmail si está pendiente de activación
        if aprendiz.estado_cuenta == EstadoCuenta.PENDIENTE:
            enviar_correo_activacion_aprendiz(
                aprendiz=aprendiz,
                ficha_numero=ficha.numero,
                nombre_grupo=nombre_grupo,
            )

        # Matricular en la ficha activa (1 matrícula activa por aprendiz)
        Matricula.objects.filter(aprendiz=aprendiz, activa=True).exclude(
            ficha=ficha
        ).update(activa=False)
        Matricula.objects.update_or_create(
            aprendiz=aprendiz,
            ficha=ficha,
            defaults={"activa": True},
        )

        # Crear u obtener el Grupo Scrum en la ficha
        grupo, _ = GrupoScrum.objects.get_or_create(
            ficha=ficha,
            nombre_grupo=nombre_grupo,
        )

        # Asignar miembro al Grupo Scrum (1 aprendiz = máximo 1 grupo)
        MiembroGrupoScrum.objects.update_or_create(
            aprendiz=aprendiz,
            defaults={"grupo": grupo},
        )

        aprendices_creados_o_vinculados.append(
            {
                "id": str(aprendiz.id),
                "documento": aprendiz.documento,
                "nombre_completo": aprendiz.nombre_completo,
                "correo": aprendiz.correo,
                "estado_cuenta": aprendiz.estado_cuenta,
                "grupo_scrum": grupo.nombre_grupo,
                "token_activacion": aprendiz.token_activacion,
            }
        )

    carga = CargaMasiva.objects.create(
        instructor=instructor,
        ficha=ficha,
        archivo=nombre_archivo,
        estado="COMPLETADA",
        alertas_duplicados=[],
    )
    return carga, aprendices_creados_o_vinculados


@transaction.atomic
def disolver_grupo_scrum(grupo: GrupoScrum) -> dict:
    """
    Regla 3.5: Si un grupo se separa o disuelve, el GrupoScrum SÍ se puede eliminar/disolver
    para reasignar a los aprendices activos, pero los aprendices jamás se eliminan.
    Limpia además el directorio del Sandbox si el grupo tenía un proyecto alojado.
    """
    nombre_grupo = grupo.nombre_grupo
    ficha_numero = grupo.ficha.numero
    aprendices_liberados = [
        {
            "id": str(m.aprendiz.id),
            "documento": m.aprendiz.documento,
            "nombre_completo": m.aprendiz.nombre_completo,
        }
        for m in grupo.miembros.select_related("aprendiz").all()
    ]

    proyecto = getattr(grupo, "proyecto", None)
    if proyecto:
        sandbox_dir = Path(settings.BASE_DIR) / "media" / "sandbox_projects" / str(proyecto.id)
        if sandbox_dir.exists():
            shutil.rmtree(sandbox_dir)

    grupo.delete()
    return {
        "nombre_grupo": nombre_grupo,
        "ficha_numero": ficha_numero,
        "aprendices_liberados": aprendices_liberados,
    }


@transaction.atomic
def conformar_o_reasignar_grupo_scrum(
    ficha: Ficha,
    nombre_grupo: str,
    documentos_aprendices: list[str],
) -> GrupoScrum:
    """
    Permite al instructor conformar un nuevo Grupo Scrum o reasignar aprendices activos
    de la ficha a un grupo, garantizando:
    - Todos los aprendices pertenecen a la ficha y no están SUSPENDIDOS.
    - El grupo resultante tiene mínimo 2 aprendices activos (Regla 3.2).
    - Ningún grupo origen queda con menos de 2 aprendices activos tras la reasignación.
    """
    nombre_limpio = " ".join(str(nombre_grupo or "").strip().split())
    if not nombre_limpio:
        raise ValidationError("El nombre del Grupo Scrum es obligatorio.")

    docs_unicos = list(dict.fromkeys(str(d).strip() for d in documentos_aprendices if str(d).strip()))
    if len(docs_unicos) < 2:
        raise ValidationError(
            "Regla SENA: Todo Grupo Scrum debe conformarse con mínimo 2 aprendices."
        )

    aprendices = list(
        Usuario.objects.filter(
            documento__in=docs_unicos,
            rol=RolUsuario.APRENDIZ,
        )
    )
    if len(aprendices) != len(docs_unicos):
        encontrados = {a.documento for a in aprendices}
        faltantes = [d for d in docs_unicos if d not in encontrados]
        raise ValidationError(
            f"No se encontraron aprendices registrados con los documentos: {', '.join(faltantes)}."
        )

    for apr in aprendices:
        if apr.estado_cuenta == EstadoCuenta.SUSPENDIDO:
            raise ValidationError(
                f"El aprendiz {apr.nombre_completo} ({apr.documento}) está SUSPENDIDO y no puede asignarse a un Grupo Scrum."
            )
        if not Matricula.objects.filter(aprendiz=apr, ficha=ficha, activa=True).exists():
            raise ValidationError(
                f"El aprendiz {apr.nombre_completo} ({apr.documento}) no tiene matrícula activa en la ficha {ficha.numero}."
            )

    grupo, _ = GrupoScrum.objects.get_or_create(
        ficha=ficha,
        nombre_grupo=nombre_limpio,
    )

    grupos_origen_afectados: set[GrupoScrum] = set()
    for apr in aprendices:
        miembro_actual = getattr(apr, "miembro_grupo_scrum", None)
        if miembro_actual and miembro_actual.grupo_id != grupo.id:
            grupos_origen_afectados.add(miembro_actual.grupo)
        MiembroGrupoScrum.objects.update_or_create(
            aprendiz=apr,
            defaults={"grupo": grupo},
        )

    # Verificar que ningún grupo origen haya quedado con 1 solo aprendiz activo
    for grupo_origen in grupos_origen_afectados:
        restantes = (
            grupo_origen.miembros.exclude(
                aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO
            ).count()
        )
        if 0 < restantes < 2:
            raise ValidationError(
                f"Reasignación rechazada: El grupo origen '{grupo_origen.nombre_grupo}' quedaría con "
                f"{restantes} aprendiz activo (mínimo requerido: 2). Disuelva ese grupo primero o reasigne a todos sus miembros."
            )

    # Verificar que el grupo destino tenga al menos 2 miembros no suspendidos
    total_destino = (
        grupo.miembros.exclude(
            aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO
        ).count()
    )
    if total_destino < 2:
        raise ValidationError(
            f"El grupo '{grupo.nombre_grupo}' debe tener mínimo 2 aprendices activos."
        )

    return grupo
