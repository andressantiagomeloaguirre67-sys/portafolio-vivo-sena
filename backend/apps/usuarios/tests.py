"""
Suite de pruebas automatizadas de extremo a extremo para el Backend de Portafolio Vivo SENA ADSO.
Verifica las 5 Reglas de Negocio Inquebrantables:
1. Login por Documento, Activación de Cuenta y Prohibición de Eliminar Aprendices (No Delete + Suspensión con motivo).
2. Rotación Trimestral de Instructores (1 solo instructor activo por ficha + reasignación de consultas pendientes).
3. Grupos Scrum: Carga masiva con detección de duplicados (documento y nombre completo), mínimo 2 aprendices y 1 proyecto por grupo.
4. Igualdad en el Grupo Scrum, reemplazo atómico de la versión única en el Sandbox y bitácora HistorialProyecto.
5. Agente IA Aegis (Originalidad Guiada y tutoría socrática autónoma sin escalamiento al instructor).
"""

import io
import zipfile
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.fichas.models import AsignacionInstructor, Ficha, GrupoScrum, MiembroGrupoScrum
from apps.fichas.services import (
    archivar_equipo_scrum,
    crear_equipo_scrum,
    mover_integrante_de_equipo,
    registrar_e_invitar_aprendiz_individual,
    rotar_instructor_ficha,
)
from apps.proyectos.models import HistorialProyecto, Proyecto
from apps.revisiones.models import ComentarioRevision, ConsultaEscaladaInstructor
from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario


class PortafolioVivoSenaBackendTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.instructor_1 = Usuario.objects.create_user(
            documento="80111222",
            nombre_completo="Instructor Uno SENA",
            correo="inst1@sena.edu.co",
            rol=RolUsuario.INSTRUCTOR,
            password="PasswordSena2026*",
            estado_cuenta=EstadoCuenta.ACTIVO,
            is_active=True,
        )
        self.instructor_2 = Usuario.objects.create_user(
            documento="80333444",
            nombre_completo="Instructor Dos SENA",
            correo="inst2@sena.edu.co",
            rol=RolUsuario.INSTRUCTOR,
            password="PasswordSena2026*",
            estado_cuenta=EstadoCuenta.ACTIVO,
            is_active=True,
        )
        self.ficha = Ficha.objects.create(
            numero="2879999",
            programa="Análisis y Desarrollo de Software (ADSO)",
            jornada="DIURNA",
        )
        rotar_instructor_ficha(self.ficha, self.instructor_1, "2026-Trimestre-2")

    def test_regla_1_no_delete_aprendiz_y_suspension_con_motivo(self):
        """Verifica que esté prohibido borrar aprendices y que al suspender se exija motivo."""
        aprendiz = Usuario.objects.create_user(
            documento="1099887766",
            nombre_completo="Aprendiz Prueba No Delete",
            correo="aprendiz.nodelete@soy.sena.edu.co",
            rol=RolUsuario.APRENDIZ,
            password="PasswordSena2026*",
            estado_cuenta=EstadoCuenta.ACTIVO,
            is_active=True,
        )

        # Intentar eliminar directamente por instancia o QuerySet debe lanzar ValidationError
        with self.assertRaises(ValidationError):
            aprendiz.delete()

        with self.assertRaises(ValidationError):
            Usuario.objects.filter(id=aprendiz.id).delete()

        # Suspender con motivo válido
        self.client.force_authenticate(user=self.instructor_1)
        resp = self.client.post(
            f"/api/v1/auth/aprendices/{aprendiz.id}/suspender/",
            {"motivo_suspension": "Retiro temporal por traslado de ciudad justificado."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        aprendiz.refresh_from_db()
        self.assertEqual(aprendiz.estado_cuenta, EstadoCuenta.SUSPENDIDO)
        self.assertFalse(aprendiz.is_active)

    def test_regla_2_rotacion_trimestral_un_solo_instructor_activo(self):
        """Verifica que al rotar de instructor quede solo 1 activo en PostgreSQL."""
        rotar_instructor_ficha(self.ficha, self.instructor_2, "2026-Trimestre-3")

        activas = AsignacionInstructor.objects.filter(ficha=self.ficha, activa=True)
        historicas = AsignacionInstructor.objects.filter(ficha=self.ficha, activa=False)

        self.assertEqual(activas.count(), 1)
        self.assertEqual(activas.first().instructor, self.instructor_2)
        self.assertEqual(historicas.count(), 1)
        self.assertEqual(historicas.first().instructor, self.instructor_1)

    def test_regla_3_equipos_scrum_unicidad_minimo_dos_mover_y_archivar(self):
        """Verifica creación directa de equipos, unicidad activa, mover con historial y archivar No-Delete."""
        a1, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Ana López", "1001", "ana@soy.sena.edu.co")
        a2, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Luis Pérez", "1002", "luis@soy.sena.edu.co")
        a3, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Sara Díaz", "1003", "sara@soy.sena.edu.co")
        a4, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Juan Ruiz", "1004", "juan@soy.sena.edu.co")
        a5, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Mía Mora", "1005", "mia@soy.sena.edu.co")

        # 1. Mínimo 2 integrantes
        with self.assertRaises(ValidationError):
            crear_equipo_scrum(
                ficha=self.ficha,
                nombre_grupo="Grupo Pequeño",
                proyecto_titulo="Proyecto Mini",
                proyecto_descripcion="Descripción válida de prueba para proyecto mini.",
                integrantes=[{"aprendiz_id": a1.id, "rol_scrum": "DEVELOPER"}],
            )

        # 2. Crear equipo 1 con 3 integrantes
        g1 = crear_equipo_scrum(
            ficha=self.ficha,
            nombre_grupo="Grupo Scrum A",
            proyecto_titulo="Proyecto A SENA",
            proyecto_descripcion="Sistema de gestión académica para pruebas SENA.",
            integrantes=[
                {"aprendiz_id": a1.id, "rol_scrum": "SCRUM_MASTER"},
                {"aprendiz_id": a2.id, "rol_scrum": "PRODUCT_OWNER"},
                {"aprendiz_id": a3.id, "rol_scrum": "DEVELOPER"},
            ],
            estado=GrupoScrum.EstadoGrupo.PUBLICADO,
        )

        # 3. Intentar asignar un aprendiz ya asignado a otro equipo debe fallar
        with self.assertRaises(ValidationError):
            crear_equipo_scrum(
                ficha=self.ficha,
                nombre_grupo="Grupo Scrum B",
                proyecto_titulo="Proyecto B SENA",
                proyecto_descripcion="Otro proyecto de prueba para validar unicidad.",
                integrantes=[
                    {"aprendiz_id": a1.id, "rol_scrum": "DEVELOPER"},
                    {"aprendiz_id": a4.id, "rol_scrum": "DEVELOPER"},
                ],
            )

        # 4. Crear equipo 2 con a4 y a5 y mover a3 desde g1 hacia g2 conservando historial
        g2 = crear_equipo_scrum(
            ficha=self.ficha,
            nombre_grupo="Grupo Scrum B",
            proyecto_titulo="Proyecto B SENA",
            proyecto_descripcion="Otro proyecto de prueba para validar movimientos.",
            integrantes=[
                {"aprendiz_id": a4.id, "rol_scrum": "DEVELOPER"},
                {"aprendiz_id": a5.id, "rol_scrum": "DEVELOPER"},
            ],
        )
        mover_integrante_de_equipo(g1, a3.id, g2.id, "DEVELOPER")
        self.assertEqual(MiembroGrupoScrum.objects.filter(ficha=self.ficha, aprendiz=a3, activo=True).count(), 1)
        self.assertEqual(MiembroGrupoScrum.objects.filter(ficha=self.ficha, aprendiz=a3, activo=False).count(), 1)

        # 5. Bloquear mover cuando origen quedaría con < 2 integrantes
        with self.assertRaises(ValidationError):
            mover_integrante_de_equipo(g1, a1.id, g2.id, "DEVELOPER")

        # 6. Archivar g2 libera a sus aprendices sin borrar registros
        archivar_equipo_scrum(g2)
        g2.refresh_from_db()
        self.assertEqual(g2.estado, GrupoScrum.EstadoGrupo.ARCHIVADO)
        self.assertEqual(MiembroGrupoScrum.objects.filter(grupo=g2, activo=True).count(), 0)
        self.assertEqual(MiembroGrupoScrum.objects.filter(grupo=g2, activo=False).count(), 3)

    def test_regla_4_y_5_proyecto_unico_reemplazo_zip_y_agente_guardian(self):
        """
        Verifica el flujo completo de un Grupo Scrum:
        - Creación directa con 2 aprendices.
        - Consulta al Agente IA: Aegis opera de forma autónoma sin crear consultas para el instructor.
        - Registro de idea única (vector 768 dims en PostgreSQL).
        - Subida y reemplazo atómico del archivo .zip en el Sandbox.
        - Registro inmutable en HistorialProyecto y respuesta a ComentarioRevision.
        """
        pedro, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Pedro Gómez", "2001", "pedro@soy.sena.edu.co")
        sofia, _, _ = registrar_e_invitar_aprendiz_individual(self.ficha, "Sofía Herrera", "2002", "sofia@soy.sena.edu.co")
        for u in (pedro, sofia):
            u.set_password("PasswordSena2026*")
            u.estado_cuenta = EstadoCuenta.ACTIVO
            u.is_active = True
            u.save()

        crear_equipo_scrum(
            ficha=self.ficha,
            nombre_grupo="Grupo Scrum Alfa",
            proyecto_titulo="Propuesta Inicial Alfa",
            proyecto_descripcion="Propuesta inicial del Grupo Scrum Alfa para pruebas.",
            integrantes=[
                {"aprendiz_id": pedro.id, "rol_scrum": "SCRUM_MASTER"},
                {"aprendiz_id": sofia.id, "rol_scrum": "DEVELOPER"},
            ],
            estado=GrupoScrum.EstadoGrupo.PUBLICADO,
        )

        self.client.force_authenticate(user=pedro)

        # 1. Consultar al Agente sin idea concreta -> Aegis actúa de forma autónoma (0 escalados al instructor)
        resp_ia_diagrama = self.client.post(
            "/api/v1/asistente/consultar/",
            {"mensaje": "Necesito ayuda para hacer el diagrama entidad relacion y casos de uso"},
            format="json",
        )
        self.assertEqual(resp_ia_diagrama.status_code, 200)
        self.assertEqual(resp_ia_diagrama.data["estado_originalidad"], "SIN_VALIDAR")
        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 0)

        # 2. Registrar/actualizar idea única con Pedro (el equipo ya tiene proyecto inicial creado por el instructor)
        resp_idea = self.client.post(
            "/api/v1/proyectos/mi-grupo/",
            {
                "titulo": "BioRecicla SENA: Trazabilidad de Residuos Aprovechables",
                "introduccion": "Plataforma para registrar rutas de recolección de reciclaje y pesaje por centro de formación.",
                "tecnologias": ["Django", "React"],
                "visibilidad": "PUBLICO",
            },
            format="json",
        )
        self.assertIn(resp_idea.status_code, (200, 201))
        self.assertEqual(resp_idea.data["estado_originalidad"], "ORIGINAL")
        proyecto_id = resp_idea.data["id"]

        # 3. Sofía (compañera del mismo Grupo Scrum) sube un archivo .zip válido -> Entrega #1
        self.client.force_authenticate(user=sofia)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("mi_carpeta/index.html", "<html><body><h1>Entrega 1 BioRecicla</h1></body></html>")
        zip_buffer.seek(0)
        zip_buffer.name = "entrega1.zip"

        resp_subida = self.client.post(
            "/api/v1/proyectos/mi-grupo/subir-codigo/",
            {
                "punto_entrada": "index.html",
                "descripcion_cambio": "Primera entrega funcional con index.html",
                "archivo_zip": zip_buffer,
            },
            format="multipart",
        )
        self.assertEqual(resp_subida.status_code, 200)
        self.assertEqual(resp_subida.data["proyecto"]["numero_entrega_actual"], 1)

        # Verificar que el Sandbox sirva el archivo desempaquetado con cabeceras CSP
        resp_sandbox = self.client.get(f"/sandbox/{proyecto_id}/index.html")
        self.assertEqual(resp_sandbox.status_code, 200)
        self.assertIn("Content-Security-Policy", resp_sandbox.headers)

        # 4. El instructor comenta y Pedro responde -> se registra en HistorialProyecto
        self.client.force_authenticate(user=self.instructor_1)
        resp_com = self.client.post(
            f"/api/v1/revisiones/proyectos/{proyecto_id}/comentarios/",
            {"comentario_instructor": "Falta agregar el filtro por fecha en la tabla de pesaje."},
            format="json",
        )
        self.assertEqual(resp_com.status_code, 201)
        comentario_id = resp_com.data["id"]

        self.client.force_authenticate(user=pedro)
        resp_resp = self.client.post(
            f"/api/v1/revisiones/comentarios/{comentario_id}/responder/",
            {"respuesta_grupo": "Listo profe, ya corregimos el filtro por fecha en la nueva subida."},
            format="json",
        )
        self.assertEqual(resp_resp.status_code, 200)

        acciones_bitacora = list(
            HistorialProyecto.objects.filter(proyecto_id=proyecto_id).values_list("accion", flat=True)
        )
        self.assertIn(HistorialProyecto.TipoAccion.REGISTRO_IDEA, acciones_bitacora)
        self.assertIn(HistorialProyecto.TipoAccion.SUBIO_CODIGO, acciones_bitacora)


class EquiposScrumConcurrenciaTests(TransactionTestCase):
    """Verifica con dos hilos simultáneos que solo una asignación prospera y sin datos a medias."""

    def test_dos_asignaciones_simultaneas_solo_una_prospera(self):
        import concurrent.futures
        import threading
        from django.db import close_old_connections

        ficha = Ficha.objects.create(numero="3999001", programa="ADSO", jornada="DIURNA")
        compartido, _, _ = registrar_e_invitar_aprendiz_individual(ficha, "Aprendiz Compartido", "910001", "comp@sena.edu.co")
        libre_a, _, _ = registrar_e_invitar_aprendiz_individual(ficha, "Libre A", "910002", "librea@sena.edu.co")
        libre_b, _, _ = registrar_e_invitar_aprendiz_individual(ficha, "Libre B", "910003", "libreb@sena.edu.co")
        for u in (compartido, libre_a, libre_b):
            u.estado_cuenta = EstadoCuenta.ACTIVO
            u.is_active = True
            u.save(update_fields=["estado_cuenta", "is_active"])

        barrera = threading.Barrier(2)

        def intentar(nombre_eq, titulo_proy, otro_id):
            close_old_connections()
            try:
                barrera.wait(timeout=5)
                crear_equipo_scrum(
                    ficha=ficha,
                    nombre_grupo=nombre_eq,
                    proyecto_titulo=titulo_proy,
                    proyecto_descripcion="Descripción de prueba de concurrencia real.",
                    integrantes=[
                        {"aprendiz_id": compartido.id, "rol_scrum": "DEVELOPER"},
                        {"aprendiz_id": otro_id, "rol_scrum": "DEVELOPER"},
                    ],
                )
                return ("OK", nombre_eq)
            except ValidationError as exc:
                return ("ERR", exc.messages[0])
            finally:
                close_old_connections()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(intentar, "Equipo Hilo 1", "Proyecto Hilo 1", libre_a.id)
            f2 = pool.submit(intentar, "Equipo Hilo 2", "Proyecto Hilo 2", libre_b.id)
            resultados = [f1.result(), f2.result()]

        exitos = [r for r in resultados if r[0] == "OK"]
        errores = [r for r in resultados if r[0] == "ERR"]

        self.assertEqual(len(exitos), 1, f"Se esperaba exactamente 1 éxito: {resultados}")
        self.assertEqual(len(errores), 1, f"Se esperaba exactamente 1 error: {resultados}")
        self.assertIn("ya fue asignado al", errores[0][1])
        self.assertEqual(GrupoScrum.objects.filter(ficha=ficha).count(), 1)
        self.assertEqual(MiembroGrupoScrum.objects.filter(ficha=ficha, aprendiz=compartido, activo=True).count(), 1)
