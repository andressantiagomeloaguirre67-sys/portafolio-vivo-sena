"""
Pruebas automatizadas del motor de Originalidad Guiada de Aegis IA (Módulo 5).
Verifica los 9 casos de la lista de verificación:
1. Idea genérica repetida ("sistema de inventario para una tienda") -> REPETIDA o SIMILAR.
2. Idea realmente original -> ORIGINAL, pregunta en 1 frase qué la hace propia, continúa a alcance/MVP.
3. Idea existente con sinónimos/renombrado -> REPETIDA (anti-evasión).
4. En choque, Aegis guía con pregunta sobre ejes de diferenciación y NO redacta proyecto ni objetivos.
5. Sin idea concreta ("Hola", "no sé de qué hacerlo", "soy principiante") -> SIN_VALIDAR, sin mencionar PostgreSQL.
6. Compara contra TODAS las fichas, jornadas, trimestres y proyectos archivados/retirados.
7. Privacidad estricta: choque con proyecto NO público (borrador o archivado) jamás filtra título, ficha, grupo ni integrantes.
8. Concurrencia real (2 hilos simultáneos con Barrier) registrando la misma idea -> 1 gana, el 2º detecta la colisión.
9. Cero trabajo al instructor: nunca crea `ConsultaEscaladaInstructor`, tickets ni notificaciones.
"""

import threading
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APITestCase

from apps.asistente.services import (
    generar_embedding_768,
    procesar_consulta_agente_guardian,
    registrar_embedding_idea_con_bloqueo,
)
from apps.fichas.models import AsignacionInstructor, Ficha, GrupoScrum, Matricula, MiembroGrupoScrum
from apps.fichas.services import archivar_equipo_scrum, crear_equipo_scrum
from apps.proyectos.models import Proyecto
from apps.revisiones.models import ConsultaEscaladaInstructor
from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario


def _crear_aprendiz_activo(doc: str, nombre: str, correo: str, ficha: Ficha) -> Usuario:
    u = Usuario.objects.create_user(
        documento=doc,
        nombre_completo=nombre,
        correo=correo,
        rol=RolUsuario.APRENDIZ,
        password="PasswordSena2026*",
        estado_cuenta=EstadoCuenta.ACTIVO,
        is_active=True,
        acepto_habeas_data=True,
    )
    Matricula.objects.create(aprendiz=u, ficha=ficha, activa=True)
    return u


class AegisOriginalidadGuiadaTests(APITestCase):
    def setUp(self):
        self.instructor = Usuario.objects.create_user(
            documento="79000101",
            nombre_completo="Carlos Mendoza",
            correo="carlos.mendoza@sena.edu.co",
            rol=RolUsuario.INSTRUCTOR,
            password="PasswordSena2026*",
            estado_cuenta=EstadoCuenta.ACTIVO,
            is_active=True,
            acepto_habeas_data=True,
        )
        self.ficha_diurna = Ficha.objects.create(
            numero="2874051", programa="ADSO", jornada="DIURNA"
        )
        self.ficha_nocturna = Ficha.objects.create(
            numero="2901182", programa="ADSO", jornada="NOCTURNA"
        )
        AsignacionInstructor.objects.create(
            ficha=self.ficha_diurna,
            instructor=self.instructor,
            trimestre="2026-Trimestre-3",
            activa=True,
        )
        AsignacionInstructor.objects.create(
            ficha=self.ficha_nocturna,
            instructor=self.instructor,
            trimestre="2026-Trimestre-3",
            activa=True,
        )

        # Aprendices y equipo público existente en ficha diurna (AgroSensor Huila)
        self.a_pub1 = _crear_aprendiz_activo("3001", "Laura Méndez", "laura.m@soy.sena.edu.co", self.ficha_diurna)
        self.a_pub2 = _crear_aprendiz_activo("3002", "Andrés Ríos", "andres.r@soy.sena.edu.co", self.ficha_diurna)
        self.grupo_publico = crear_equipo_scrum(
            ficha=self.ficha_diurna,
            nombre_grupo="Grupo Scrum Agro",
            proyecto_titulo="AgroSensor Huila: Monitoreo de Humedad y Riego para Caficultores",
            proyecto_descripcion="Plataforma con sensores de humedad y control de riego para cultivos de café en fincas del Huila.",
            integrantes=[
                {"aprendiz_id": self.a_pub1.id, "rol_scrum": "SCRUM_MASTER"},
                {"aprendiz_id": self.a_pub2.id, "rol_scrum": "DEVELOPER"},
            ],
            estado=GrupoScrum.EstadoGrupo.PUBLICADO,
        )

        # Aprendiz de prueba en otra ficha (NOCTURNA) consultando a Aegis
        self.aprendiz_chat = _crear_aprendiz_activo("3099", "Valentina Torres", "valen.t@soy.sena.edu.co", self.ficha_nocturna)
        self.client = APIClient()
        self.client.force_authenticate(user=self.aprendiz_chat)

    def test_1_idea_generica_inventario_tienda_detecta_choque(self):
        """Caso 1: Proponer 'sistema de inventario para una tienda' -> REPETIDA o SIMILAR."""
        resp = self.client.post(
            "/api/v1/asistente/consultar/",
            {"mensaje": "Quiero hacer un sistema de inventario para una tienda"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(resp.data["estado_originalidad"], ("REPETIDA", "SIMILAR"))
        self.assertFalse(resp.data["es_idea_unica"])
        self.assertIn(resp.data["etiqueta_originalidad"], ("Repetida: replantear", "Similar: por diferenciar"))
        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 0)

    def test_2_idea_original_confirma_pide_frase_y_continua_mvp(self):
        """Caso 2: Idea realmente original -> ORIGINAL, pregunta qué la hace propia y continúa a alcance/MVP."""
        msg1 = (
            "Queremos construir una red comunitaria offline por Bluetooth y QR para trueque "
            "de semillas criollas entre mujeres rurales del Cauca sin señal móvil"
        )
        r1 = self.client.post(
            "/api/v1/asistente/consultar/",
            {"mensaje": msg1},
            format="json",
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["estado_originalidad"], "ORIGINAL")
        self.assertEqual(r1.data["etiqueta_originalidad"], "Original")
        self.assertTrue(r1.data["es_idea_unica"])
        self.assertIn("una sola frase", r1.data["respuesta"].lower())

        # Turno 2: el aprendiz responde qué la hace propia -> Aegis pasa a Prioridad #2 (alcance/MVP)
        historial = [
            {
                "mensaje_usuario": msg1,
                "respuesta_agente": r1.data["respuesta"],
                "estado_originalidad": r1.data["estado_originalidad"],
            }
        ]
        r2 = self.client.post(
            "/api/v1/asistente/consultar/",
            {
                "mensaje": "La hace propia que funciona sin internet y preserva variedades nativas entre mujeres campesinas.",
                "historial": historial,
            },
            format="json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["estado_originalidad"], "ORIGINAL")
        self.assertEqual(r2.data["accion_agente"], "TUTORIA_SOCRATICA_PROYECTO")
        self.assertIn("mvp", r2.data["respuesta"].lower())
        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 0)

    def test_3_evasion_por_sinonimos_y_renombrado_detecta_repetida(self):
        """Caso 3: Idea existente con sinónimos y otro nombre -> detectada como REPETIDA."""
        resp = self.client.post(
            "/api/v1/asistente/consultar/",
            {
                "titulo_propuesto": "CafeAgua Pro",
                "mensaje": "Aplicación para control de irrigación y medición de humedad en cultivos de café usando sensores",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["estado_originalidad"], "REPETIDA")
        self.assertFalse(resp.data["es_idea_unica"])
        # Como AgroSensor Huila SÍ es público en Vitrina, puede nombrarse
        self.assertIn("AgroSensor Huila", resp.data["respuesta"])

    def test_4_choque_guia_por_ejes_sin_redactar_proyecto_ni_objetivos(self):
        """Caso 4: En choque, Aegis pregunta por ejes de diferenciación y NO redacta el proyecto/objetivos."""
        resp = self.client.post(
            "/api/v1/asistente/consultar/",
            {"mensaje": "Quiero hacer un sistema de inventario para una tienda"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        texto = resp.data["respuesta"]
        self.assertIn(
            resp.data["eje_diferenciacion"],
            {"usuario_objetivo", "problema_especifico", "contexto_territorio", "funcion_central", "restricciones_reales"},
        )
        self.assertIn("?", texto)
        self.assertNotIn("objetivo general:", texto.lower())
        self.assertNotIn("objetivos específicos:", texto.lower())

        # Si el aprendiz pide explícitamente que le redacten los objetivos o código -> límite pedagógico
        resp_lim = self.client.post(
            "/api/v1/asistente/consultar/",
            {"mensaje": "Redáctame el proyecto y hazme los objetivos por favor"},
            format="json",
        )
        self.assertEqual(resp_lim.status_code, 200)
        self.assertEqual(resp_lim.data["accion_agente"], "LIMITE_PEDAGOGICO_IA")
        self.assertIn("no puedo", resp_lim.data["respuesta"].lower())

    def test_5_mensajes_sin_idea_concreta_no_validan_ni_mencionan_postgresql(self):
        """Caso 5: 'Hola', 'no sé de qué hacerlo', 'soy principiante' -> SIN_VALIDAR y sin PostgreSQL."""
        for msg in (
            "Hola",
            "No sé de qué hacerlo, apenas estoy empezando",
            "Soy principiante en programación y todo es confuso",
            "Quiero hacer algo para una tienda",
        ):
            resp = self.client.post(
                "/api/v1/asistente/consultar/",
                {"mensaje": msg},
                format="json",
            )
            self.assertEqual(resp.status_code, 200, msg=f"Fallo en mensaje: {msg}")
            self.assertEqual(resp.data["estado_originalidad"], "SIN_VALIDAR", msg=f"Mensaje validó sin idea: {msg}")
            self.assertEqual(resp.data["etiqueta_originalidad"], "Sin validar")
            self.assertIsNone(resp.data["es_idea_unica"])
            self.assertNotIn("postgresql", resp.data["respuesta"].lower())
            self.assertNotIn("vía libre", resp.data["respuesta"].lower())
        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 0)

    def test_6_y_7_compara_otras_fichas_y_archivados_con_privacidad_estricta(self):
        """
        Casos 6 y 7:
        - Crea un proyecto BORRADOR (no público) en ficha DIURNA y un proyecto ARCHIVADO en ficha NOCTURNA.
        - Verifica que ambos SÍ se comparan desde otra ficha/jornada.
        - Verifica que NUNCA se filtra el título, nombre de grupo, ficha ni integrantes en JSON ni en texto.
        """
        # Proyecto BORRADOR privado en ficha DIURNA
        a_priv1 = _crear_aprendiz_activo("3010", "Camila Privada", "camila.p@soy.sena.edu.co", self.ficha_diurna)
        a_priv2 = _crear_aprendiz_activo("3011", "Mateo Privado", "mateo.p@soy.sena.edu.co", self.ficha_diurna)
        crear_equipo_scrum(
            ficha=self.ficha_diurna,
            nombre_grupo="Equipo Secreto Borrador",
            proyecto_titulo="OrtoBanco Secreto: Préstamo de Sillas de Ruedas y Muletas",
            proyecto_descripcion="Plataforma comunitaria para préstamo rotativo de sillas de ruedas, muletas y caminadores ortopédicos con control de mantenimiento preventivo.",
            integrantes=[
                {"aprendiz_id": a_priv1.id, "rol_scrum": "SCRUM_MASTER"},
                {"aprendiz_id": a_priv2.id, "rol_scrum": "DEVELOPER"},
            ],
            estado=GrupoScrum.EstadoGrupo.BORRADOR,
        )

        # Proyecto ARCHIVADO en ficha NOCTURNA (regla No-Delete: historial sigue contando)
        a_arch1 = _crear_aprendiz_activo("3020", "Diego Archivado", "diego.a@soy.sena.edu.co", self.ficha_nocturna)
        a_arch2 = _crear_aprendiz_activo("3021", "Lucía Archivada", "lucia.a@soy.sena.edu.co", self.ficha_nocturna)
        grupo_arch = crear_equipo_scrum(
            ficha=self.ficha_nocturna,
            nombre_grupo="Equipo Histórico Archivado",
            proyecto_titulo="ApicultorNube Secreto: Trazabilidad de Colmenas y Miel",
            proyecto_descripcion="Registro digital de colmenas de abejas, floración y trazabilidad de producción de miel artesanal por apiario.",
            integrantes=[
                {"aprendiz_id": a_arch1.id, "rol_scrum": "SCRUM_MASTER"},
                {"aprendiz_id": a_arch2.id, "rol_scrum": "DEVELOPER"},
            ],
            estado=GrupoScrum.EstadoGrupo.PUBLICADO,
        )
        archivar_equipo_scrum(grupo_arch)

        # Consulta chocando contra proyecto BORRADOR (desde ficha NOCTURNA)
        r_borrador = self.client.post(
            "/api/v1/asistente/consultar/",
            {
                "mensaje": "Queremos una plataforma para préstamo rotativo de sillas de ruedas, muletas y caminadores ortopédicos con mantenimiento preventivo"
            },
            format="json",
        )
        self.assertEqual(r_borrador.status_code, 200)
        self.assertIn(r_borrador.data["estado_originalidad"], ("SIMILAR", "REPETIDA"))
        payload_str_b = str(r_borrador.data)
        for secreto in ("OrtoBanco Secreto", "Equipo Secreto Borrador", "Camila Privada", "Mateo Privado", "2874051"):
            self.assertNotIn(secreto, payload_str_b)

        # Consulta chocando contra proyecto ARCHIVADO
        r_arch = self.client.post(
            "/api/v1/asistente/consultar/",
            {
                "mensaje": "Aplicación de registro digital de colmenas de abejas, floración y trazabilidad de producción de miel artesanal por apiario"
            },
            format="json",
        )
        self.assertEqual(r_arch.status_code, 200)
        self.assertIn(r_arch.data["estado_originalidad"], ("SIMILAR", "REPETIDA"))
        payload_str_a = str(r_arch.data)
        for secreto in ("ApicultorNube Secreto", "Equipo Histórico Archivado", "Diego Archivado", "Lucía Archivada", "2901182"):
            self.assertNotIn(secreto, payload_str_a)

        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 0)

    def test_9_tutoria_ia_eliminada_redirecciones_y_endpoints_retirados(self):
        """
        Verifica eliminación completa de Tutoría IA del panel del instructor:
        - URLs antiguas de Tutoría IA redirigen (302) a Resumen de la ficha.
        - Endpoints /revisiones/consultas-escaladas/ y .../responder/ responden 404.
        - /revisiones/resumen-instructor/ no incluye consultas_ia_pendientes.
        - Consultas históricas archivadas conservan sus datos bajo No-Delete.
        """
        import uuid
        from django.urls import Resolver404, resolve

        r_red1 = self.client.get("/instructor/fichas/2874051/tutoria")
        self.assertEqual(r_red1.status_code, 302)
        self.assertEqual(r_red1["Location"], "/instructor/fichas/2874051/resumen")

        r_red2 = self.client.get("/fichas/2874051/tutoria/")
        self.assertEqual(r_red2.status_code, 302)
        self.assertEqual(r_red2["Location"], "/instructor/fichas/2874051/resumen")

        with self.assertRaises(Resolver404):
            resolve("/api/v1/revisiones/consultas-escaladas/")
        with self.assertRaises(Resolver404):
            resolve(f"/api/v1/revisiones/consultas-escaladas/{uuid.uuid4()}/responder/")

        self.client.force_authenticate(user=self.instructor)
        r_resumen = self.client.get("/api/v1/revisiones/resumen-instructor/")
        self.assertEqual(r_resumen.status_code, 200)
        self.assertNotIn("consultas_ia_pendientes", r_resumen.data)

        # Verificar estado archivado por cambio de política (No-Delete)
        archivo = ConsultaEscaladaInstructor.objects.create(
            ficha=self.ficha_diurna,
            aprendiz=self.aprendiz_chat,
            instructor_destino=self.instructor,
            mensaje_original_aprendiz="Consulta histórica de ejemplo",
            estado=ConsultaEscaladaInstructor.EstadoConsulta.ARCHIVADA_POR_CAMBIO_DE_POLITICA,
        )
        self.assertEqual(archivo.estado, "archivada_por_cambio_de_politica")


class AegisConcurrenciaOriginalidadTests(TransactionTestCase):
    def test_8_registro_concurrente_dos_equipos_misma_idea_detecta_colision(self):
        """
        Caso 8: Dos equipos intentan registrar simultáneamente la misma idea original.
        Con `pg_advisory_xact_lock`, exactamente 1 gana y el 2º falla con colisión limpia.
        """
        ficha = Ficha.objects.create(numero="2999991", programa="ADSO", jornada="DIURNA")
        u1 = _crear_aprendiz_activo("4001", "Ana Uno", "ana1@soy.sena.edu.co", ficha)
        u2 = _crear_aprendiz_activo("4002", "Luis Dos", "luis2@soy.sena.edu.co", ficha)
        u3 = _crear_aprendiz_activo("4003", "Sara Tres", "sara3@soy.sena.edu.co", ficha)
        u4 = _crear_aprendiz_activo("4004", "Omar Cuatro", "omar4@soy.sena.edu.co", ficha)

        g1 = GrupoScrum.objects.create(ficha=ficha, nombre_grupo="Equipo Concurrente A", estado=GrupoScrum.EstadoGrupo.BORRADOR)
        g2 = GrupoScrum.objects.create(ficha=ficha, nombre_grupo="Equipo Concurrente B", estado=GrupoScrum.EstadoGrupo.BORRADOR)
        for g, pair in ((g1, (u1, u2)), (g2, (u3, u4))):
            for apr in pair:
                MiembroGrupoScrum.objects.create(ficha=ficha, grupo=g, aprendiz=apr, activo=True)

        barrier = threading.Barrier(2)
        resultados = []

        def intentar(grupo, sufijo_titulo):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                registrar_embedding_idea_con_bloqueo(
                    grupo=grupo,
                    titulo=f"SemillaTrueque Cauca {sufijo_titulo}",
                    introduccion=(
                        "Red comunitaria offline por Bluetooth y QR para trueque de semillas "
                        "criollas entre mujeres rurales del Cauca sin señal móvil."
                    ),
                )
                resultados.append(("OK", grupo.nombre_grupo))
            except ValidationError as exc:
                resultados.append(("COLISION", exc.messages[0]))
            finally:
                close_old_connections()

        t1 = threading.Thread(target=intentar, args=(g1, "Alpha"))
        t2 = threading.Thread(target=intentar, args=(g2, "Beta"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        exitos = [r for r in resultados if r[0] == "OK"]
        colisiones = [r for r in resultados if r[0] == "COLISION"]

        self.assertEqual(len(exitos), 1, f"Resultados inesperados: {resultados}")
        self.assertEqual(len(colisiones), 1, f"Resultados inesperados: {resultados}")
        self.assertEqual(Proyecto.objects.filter(ficha=ficha).count(), 1)
        # Privacidad: como el ganador quedó con visibilidad FICHA (no publicado en Vitrina),
        # el mensaje de colisión NO debe filtrar el título del ganador
        self.assertNotIn("SemillaTrueque Cauca", colisiones[0][1])
        self.assertEqual(ConsultaEscaladaInstructor.objects.count(), 0)
