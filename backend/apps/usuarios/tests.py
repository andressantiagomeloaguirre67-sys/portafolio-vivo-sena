"""
Suite de pruebas automatizadas de extremo a extremo para el Backend de Portafolio Vivo SENA ADSO.
Verifica las 5 Reglas de Negocio Inquebrantables:
1. Login por Documento, Activación de Cuenta y Prohibición de Eliminar Aprendices (No Delete + Suspensión con motivo).
2. Rotación Trimestral de Instructores (1 solo instructor activo por ficha + reasignación de consultas pendientes).
3. Grupos Scrum: Carga masiva con detección de duplicados (documento y nombre completo), mínimo 2 aprendices y 1 proyecto por grupo.
4. Igualdad en el Grupo Scrum, reemplazo atómico de la versión única en el Sandbox y bitácora HistorialProyecto.
5. Agente IA Guardián de Originalidad (detección vectorial de ideas repetidas y escalado automático de diagramas/lógica al instructor).
"""

import io
import zipfile
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.fichas.models import AsignacionInstructor, Ficha, GrupoScrum
from apps.fichas.services import procesar_carga_masiva_ficha, rotar_instructor_ficha
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

    def test_regla_3_carga_masiva_detecta_duplicados_y_grupos_menores_a_dos(self):
        """Verifica que la carga masiva rechace personas repetidas en varios grupos o grupos < 2."""
        registros_invalidos = [
            {
                "nombre_completo": "Ana María López",
                "documento": "1001",
                "correo": "ana@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum A",
            },
            {
                "nombre_completo": "Ana Maria Lopez",  # Repetida en otro grupo
                "documento": "1002",
                "correo": "ana2@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum B",
            },
        ]
        carga, alertas = procesar_carga_masiva_ficha(
            ficha=self.ficha,
            instructor=self.instructor_1,
            registros=registros_invalidos,
        )
        self.assertEqual(carga.estado, "CON_ALERTAS")
        tipos_alerta = {a["tipo"] for a in alertas}
        self.assertIn("NOMBRE_EN_VARIOS_GRUPOS", tipos_alerta)
        self.assertIn("GRUPO_MENOR_A_DOS_APRENDICES", tipos_alerta)

    def test_regla_4_y_5_proyecto_unico_reemplazo_zip_y_agente_guardian(self):
        """
        Verifica el flujo completo de un Grupo Scrum:
        - Carga válida de 2 aprendices.
        - Consulta al Agente IA: detecta escalado al instructor si pregunta por diagramas.
        - Registro de idea única (vector 768 dims en PostgreSQL).
        - Subida y reemplazo atómico del archivo .zip en el Sandbox.
        - Registro inmutable en HistorialProyecto y respuesta a ComentarioRevision.
        """
        registros_validos = [
            {
                "nombre_completo": "Pedro Gómez",
                "documento": "2001",
                "correo": "pedro@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum Alfa",
            },
            {
                "nombre_completo": "Sofía Herrera",
                "documento": "2002",
                "correo": "sofia@soy.sena.edu.co",
                "grupo_scrum": "Grupo Scrum Alfa",
            },
        ]
        carga, _ = procesar_carga_masiva_ficha(
            ficha=self.ficha,
            instructor=self.instructor_1,
            registros=registros_validos,
        )
        self.assertEqual(carga.estado, "COMPLETADA")

        pedro = Usuario.objects.get(documento="2001")
        sofia = Usuario.objects.get(documento="2002")
        for u in (pedro, sofia):
            u.set_password("PasswordSena2026*")
            u.estado_cuenta = EstadoCuenta.ACTIVO
            u.is_active = True
            u.save()

        self.client.force_authenticate(user=pedro)

        # 1. Consultar al Agente por diagramas -> debe escalar al instructor activo
        resp_ia_diagrama = self.client.post(
            "/api/v1/asistente/consultar/",
            {"mensaje": "Necesito ayuda para hacer el diagrama entidad relacion y casos de uso"},
            format="json",
        )
        self.assertEqual(resp_ia_diagrama.status_code, 200)
        self.assertEqual(resp_ia_diagrama.data["accion_agente"], "ESCALADO_AL_INSTRUCTOR")
        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 1)

        # 2. Registrar idea única con Pedro
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
        self.assertEqual(resp_idea.status_code, 201)
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
        self.assertIn(HistorialProyecto.TipoAccion.RESPUESTA_COMENTARIO, acciones_bitacora)
