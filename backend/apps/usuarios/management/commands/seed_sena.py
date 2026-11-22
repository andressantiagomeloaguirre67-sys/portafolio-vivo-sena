"""
Comando de inicialización de datos reales de demostración para Portafolio Vivo SENA ADSO.
Uso: python manage.py seed_sena
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.asistente.services import generar_embedding_768
from apps.fichas.models import Ficha, GrupoScrum, MiembroGrupoScrum
from apps.fichas.services import (
    registrar_e_invitar_aprendiz_individual,
    rotar_instructor_ficha,
)
from apps.proyectos.models import HistorialProyecto, Proyecto
from apps.proyectos.services import validar_y_reemplazar_entrega_unica
from apps.revisiones.models import ComentarioRevision
from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario


class Command(BaseCommand):
    help = "Puebla PostgreSQL con datos iniciales completos de Portafolio Vivo SENA ADSO."

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Superusuario / Administrador SENA
        admin_user, creado = Usuario.objects.get_or_create(
            documento="10000001",
            defaults={
                "nombre_completo": "Coordinación Académica ADSO",
                "correo": "coordinacion.adso@sena.edu.co",
                "rol": RolUsuario.ADMIN,
                "estado_cuenta": EstadoCuenta.ACTIVO,
                "is_active": True,
                "is_staff": True,
                "is_superuser": True,
                "acepto_habeas_data": True,
            },
        )
        if creado:
            admin_user.set_password("Sena2026*")
            admin_user.save(update_fields=["password"])

        # 2. Instructores SENA (Para demostrar rotación trimestral y 1 instructor -> múltiples fichas)
        inst_carlos, creado = Usuario.objects.get_or_create(
            documento="79888111",
            defaults={
                "nombre_completo": "Ing. Carlos Andrés Gómez (Instructor Líder)",
                "correo": "cgomez.instructor@sena.edu.co",
                "rol": RolUsuario.INSTRUCTOR,
                "estado_cuenta": EstadoCuenta.ACTIVO,
                "is_active": True,
                "is_staff": True,
                "acepto_habeas_data": True,
            },
        )
        if creado:
            inst_carlos.set_password("Sena2026*")
            inst_carlos.save(update_fields=["password"])

        inst_diana, creado = Usuario.objects.get_or_create(
            documento="52999222",
            defaults={
                "nombre_completo": "Ing. Diana Marcela Rojas (Instructora Arquitectura)",
                "correo": "drojas.instructora@sena.edu.co",
                "rol": RolUsuario.INSTRUCTOR,
                "estado_cuenta": EstadoCuenta.ACTIVO,
                "is_active": True,
                "is_staff": True,
                "acepto_habeas_data": True,
            },
        )
        if creado:
            inst_diana.set_password("Sena2026*")
            inst_diana.save(update_fields=["password"])

        # 3. Fichas ADSO y Rotación Trimestral (Trimestre 2 -> Diana, Trimestre 3 actual -> Carlos)
        ficha_2874051, _ = Ficha.objects.get_or_create(
            numero="2874051",
            defaults={
                "programa": "Análisis y Desarrollo de Software (ADSO)",
                "jornada": "DIURNA",
                "activa": True,
            },
        )
        ficha_2901182, _ = Ficha.objects.get_or_create(
            numero="2901182",
            defaults={
                "programa": "Análisis y Desarrollo de Software (ADSO)",
                "jornada": "NOCTURNA",
                "activa": True,
            },
        )

        if not ficha_2874051.asignaciones.exists():
            rotar_instructor_ficha(ficha_2874051, inst_diana, "2026-Trimestre-2")
            rotar_instructor_ficha(ficha_2874051, inst_carlos, "2026-Trimestre-3")

        if not ficha_2901182.asignaciones.exists():
            rotar_instructor_ficha(ficha_2901182, inst_carlos, "2026-Trimestre-3")

        # 4. Carga masiva de Aprendices y Grupos Scrum en Ficha 2874051
        registros_ficha = [
            {
                "nombre_completo": "Laura Valentina Martínez",
                "documento": "1012345678",
                "correo": "lvmartinez@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 1 - AgroTech",
            },
            {
                "nombre_completo": "Juan Sebastián Torres",
                "documento": "1023456789",
                "correo": "jstorres@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 1 - AgroTech",
            },
            {
                "nombre_completo": "Camila Andrea Quintero",
                "documento": "1034567890",
                "correo": "caquintero@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 2 - MediTurnos",
            },
            {
                "nombre_completo": "Mateo Alejandro Vargas",
                "documento": "1045678901",
                "correo": "mavargas@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 2 - MediTurnos",
            },
            {
                "nombre_completo": "Daniel Felipe Córdoba",
                "documento": "1056789012",
                "correo": "dfcordoba@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 2 - MediTurnos",
            },
        ]
        if not ficha_2874051.grupos_scrum.exists():
            for reg in registros_ficha:
                apr, _, _ = registrar_e_invitar_aprendiz_individual(
                    ficha=ficha_2874051,
                    nombre_completo=reg["nombre_completo"],
                    documento=reg["documento"],
                    correo=reg["correo"],
                )
                grupo_obj, _ = GrupoScrum.objects.get_or_create(
                    ficha=ficha_2874051,
                    nombre_grupo=reg["grupo_scrum"],
                    defaults={"estado": GrupoScrum.EstadoGrupo.PUBLICADO},
                )
                MiembroGrupoScrum.objects.get_or_create(
                    ficha=ficha_2874051,
                    aprendiz=apr,
                    activo=True,
                    defaults={"grupo": grupo_obj},
                )

        # Activar las cuentas de los primeros 4 aprendices con clave por defecto "Sena2026*"
        for doc in ("1012345678", "1023456789", "1034567890", "1045678901"):
            apr = Usuario.objects.filter(documento=doc).first()
            if apr and apr.estado_cuenta != EstadoCuenta.ACTIVO:
                apr.set_password("Sena2026*")
                apr.estado_cuenta = EstadoCuenta.ACTIVO
                apr.is_active = True
                apr.acepto_habeas_data = True
                apr.token_activacion = ""
                apr.save()

        # Suspender a Daniel Felipe Córdoba dejando motivo obligatorio (Regla 1 No Delete)
        daniel = Usuario.objects.filter(documento="1056789012").first()
        if daniel and daniel.estado_cuenta != EstadoCuenta.SUSPENDIDO:
            daniel.suspender_aprendiz(
                motivo="Aplazamiento de trimestre por calamidad doméstica soportada en coordinación académica.",
                actor=inst_carlos,
            )

        # 5. Crear Proyectos únicos por Grupo Scrum con su entrega alojada en el Sandbox
        laura = Usuario.objects.get(documento="1012345678")
        juan = Usuario.objects.get(documento="1023456789")
        camila = Usuario.objects.get(documento="1034567890")

        grupo_1 = GrupoScrum.objects.get(
            ficha=ficha_2874051, nombre_grupo="Grupo Scrum 1 - AgroTech"
        )
        grupo_2 = GrupoScrum.objects.get(
            ficha=ficha_2874051, nombre_grupo="Grupo Scrum 2 - MediTurnos"
        )

        if not hasattr(grupo_1, "proyecto"):
            titulo_1 = "AgroSensor Huila: Monitoreo de Humedad y Riego para Caficultores"
            intro_1 = (
                "Plataforma web para pequeños productores de café que permite registrar "
                "lecturas de sensores de humedad del suelo, programar alertas de riego por lote "
                "y estimar el consumo hídrico semanal."
            )
            proy_1 = Proyecto.objects.create(
                ficha=ficha_2874051,
                grupo_scrum=grupo_1,
                titulo=titulo_1,
                introduccion=intro_1,
                embedding_idea=generar_embedding_768(f"{titulo_1} {intro_1}"),
                tecnologias=["Python", "Django", "TypeScript", "Tailwind CSS", "PostgreSQL"],
                numero_entrega_actual=2,
                estado_procesamiento_zip="LISTO",
                estado=Proyecto.EstadoProyecto.PUBLICADO,
                visibilidad=Proyecto.Visibilidad.PUBLICO,
            )
            proy_1.ruta_codigo_actual = validar_y_reemplazar_entrega_unica(proy_1)
            proy_1.save(update_fields=["ruta_codigo_actual"])

            HistorialProyecto.objects.create(
                proyecto=proy_1,
                realizado_por=laura,
                accion=HistorialProyecto.TipoAccion.REGISTRO_IDEA,
                numero_entrega=0,
                descripcion_cambio="Registró la idea única del proyecto validada con el Agente Guardián.",
            )
            HistorialProyecto.objects.create(
                proyecto=proy_1,
                realizado_por=juan,
                accion=HistorialProyecto.TipoAccion.SUBIO_CODIGO,
                numero_entrega=2,
                descripcion_cambio="Subió la Entrega #2 corrigiendo la validación del formulario de lotes cafeteros.",
            )

            ComentarioRevision.objects.create(
                proyecto=proy_1,
                instructor=inst_carlos,
                numero_entrega_revisada=1,
                comentario_instructor="Excelente interfaz. Por favor agreguen validación de rangos (0% a 100%) en el sensor de humedad.",
                respuesta_grupo="Gracias profe, ya se corrigió en esta subida (Entrega #2) y se reemplazó el archivo.",
                respondido_por=juan,
                fecha_respuesta=timezone.now(),
                corregido_en_entrega=2,
            )

        if not hasattr(grupo_2, "proyecto"):
            titulo_2 = "MediTurnos Rural: Gestión de Citas Odontológicas y Triage Comunitario"
            intro_2 = (
                "Aplicación para centros de salud veredales que organiza el agendamiento "
                "de citas odontológicas, recordatorios comunitarios y control de consultorios."
            )
            proy_2 = Proyecto.objects.create(
                ficha=ficha_2874051,
                grupo_scrum=grupo_2,
                titulo=titulo_2,
                introduccion=intro_2,
                embedding_idea=generar_embedding_768(f"{titulo_2} {intro_2}"),
                tecnologias=["React", "TypeScript", "Django REST", "PostgreSQL"],
                numero_entrega_actual=1,
                estado_procesamiento_zip="LISTO",
                estado=Proyecto.EstadoProyecto.PUBLICADO,
                visibilidad=Proyecto.Visibilidad.PUBLICO,
            )
            proy_2.ruta_codigo_actual = validar_y_reemplazar_entrega_unica(proy_2)
            proy_2.save(update_fields=["ruta_codigo_actual"])

            HistorialProyecto.objects.create(
                proyecto=proy_2,
                realizado_por=camila,
                accion=HistorialProyecto.TipoAccion.SUBIO_CODIGO,
                numero_entrega=1,
                descripcion_cambio="Publicó la primera versión funcional del módulo de agendamiento.",
            )

        # 6. Poblar también la Ficha 2901182 (Nocturna) con Aprendices activos, Grupos Scrum y Proyecto
        registros_ficha_nocturna = [
            {
                "nombre_completo": "Sofía Alejandra Pineda",
                "documento": "1067890123",
                "correo": "sapineda@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 1 - LogiRutas",
            },
            {
                "nombre_completo": "Santiago Andrés Morales",
                "documento": "1078901234",
                "correo": "samorales@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 1 - LogiRutas",
            },
            {
                "nombre_completo": "Valentina Gómez Ríos",
                "documento": "1089012345",
                "correo": "vgomez@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 2 - VetCare",
            },
            {
                "nombre_completo": "Nicolás David Herrera",
                "documento": "1090123456",
                "correo": "ndherrera@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum 2 - VetCare",
            },
        ]
        if not ficha_2901182.grupos_scrum.exists():
            for reg in registros_ficha_nocturna:
                apr, _, _ = registrar_e_invitar_aprendiz_individual(
                    ficha=ficha_2901182,
                    nombre_completo=reg["nombre_completo"],
                    documento=reg["documento"],
                    correo=reg["correo"],
                )
                grupo_obj, _ = GrupoScrum.objects.get_or_create(
                    ficha=ficha_2901182,
                    nombre_grupo=reg["grupo_scrum"],
                    defaults={"estado": GrupoScrum.EstadoGrupo.PUBLICADO},
                )
                MiembroGrupoScrum.objects.get_or_create(
                    ficha=ficha_2901182,
                    aprendiz=apr,
                    activo=True,
                    defaults={"grupo": grupo_obj},
                )
            for doc in ("1067890123", "1078901234", "1089012345", "1090123456"):
                apr_noc = Usuario.objects.filter(documento=doc).first()
                if apr_noc:
                    apr_noc.set_password("Sena2026*")
                    apr_noc.estado_cuenta = EstadoCuenta.ACTIVO
                    apr_noc.is_active = True
                    apr_noc.acepto_habeas_data = True
                    apr_noc.token_activacion = ""
                    apr_noc.save()

            grupo_noc_1 = GrupoScrum.objects.get(
                ficha=ficha_2901182, nombre_grupo="Grupo Scrum 1 - LogiRutas"
            )
            sofia = Usuario.objects.get(documento="1067890123")
            titulo_noc = "LogiRutas Urbano: Control de Despachos y Entregas para Cooperativas"
            intro_noc = (
                "Sistema web para cooperativas de transporte local que registra despachos diarios, "
                "estado de entrega por ruta y novedades de conductores en tiempo real."
            )
            proy_noc = Proyecto.objects.create(
                ficha=ficha_2901182,
                grupo_scrum=grupo_noc_1,
                titulo=titulo_noc,
                introduccion=intro_noc,
                embedding_idea=generar_embedding_768(f"{titulo_noc} {intro_noc}"),
                tecnologias=["Python", "Django", "PostgreSQL", "Tailwind CSS"],
                numero_entrega_actual=1,
                estado_procesamiento_zip="LISTO",
                estado=Proyecto.EstadoProyecto.PUBLICADO,
                visibilidad=Proyecto.Visibilidad.PUBLICO,
            )
            proy_noc.ruta_codigo_actual = validar_y_reemplazar_entrega_unica(proy_noc)
            proy_noc.save(update_fields=["ruta_codigo_actual"])
            HistorialProyecto.objects.create(
                proyecto=proy_noc,
                realizado_por=sofia,
                accion=HistorialProyecto.TipoAccion.SUBIO_CODIGO,
                numero_entrega=1,
                descripcion_cambio="Publicó la primera entrega funcional del control de despachos.",
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Semilla SENA ADSO ejecutada exitosamente (Admin, Instructores, Fichas, Grupos Scrum, Proyectos y Revisiones)."
            )
        )
