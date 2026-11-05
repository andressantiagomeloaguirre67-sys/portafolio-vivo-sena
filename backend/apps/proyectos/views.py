import mimetypes
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.asistente.services import (
    buscar_proyectos_similares,
    generar_embedding_768,
)
from apps.usuarios.models import EstadoCuenta, RolUsuario
from apps.usuarios.permissions import EsAprendizActivo, EsInstructorOAdmin
from .models import HistorialProyecto, Proyecto
from .serializers import (
    HistorialProyectoSerializer,
    ProyectoFeedSerializer,
    ReemplazarCodigoProyectoSerializer,
    RegistrarOActualizarIdeaProyectoSerializer,
    RetirarProyectoInstructorSerializer,
    ValidarIdeaProyectoSerializer,
)
from .services import (
    SANDBOX_ROOT,
    limpiar_almacenamiento_proyecto,
    validar_y_reemplazar_entrega_unica,
)


class SandboxEjecucionProyectoView(APIView):
    """
    GET /sandbox/<uuid:proyecto_id>/<path:recurso>
    Sirve los archivos estáticos de la única versión alojada del proyecto con cabeceras CSP
    de aislamiento para ejecutarse de forma segura en el iframe del Feed.
    """

    permission_classes = [AllowAny]

    def get(self, request, proyecto_id, recurso="index.html"):
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        if proyecto.estado in (
            Proyecto.EstadoProyecto.ELIMINADO_POR_GRUPO,
            Proyecto.EstadoProyecto.RETIRADO_INSTRUCTOR,
        ):
            raise Http404("Este proyecto fue retirado y ya no tiene archivos alojados en el Sandbox.")

        carpeta = (SANDBOX_ROOT / str(proyecto.id)).resolve()
        archivo = (carpeta / (recurso or "index.html")).resolve()

        if not str(archivo).startswith(str(carpeta)) or not archivo.is_file():
            raise Http404("Archivo no encontrado en el Sandbox del proyecto.")

        content_type, _ = mimetypes.guess_type(str(archivo))
        response = FileResponse(
            open(archivo, "rb"),
            content_type=content_type or "text/html",
        )
        # Cabeceras de aislamiento CSP idénticas a nginx/sandbox.conf
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
            "img-src 'self' data: blob: https:; connect-src 'none';"
        )
        return response


class FeedProyectosListView(generics.ListAPIView):
    """
    GET /api/v1/proyectos/feed/
    Lista los proyectos activos en el Feed con soporte de búsqueda y filtros:
    - `?ficha_id=<uuid>` o `?ficha_numero=2874051`
    - `?estado=PUBLICADO`
    - `?tecnologia=React`
    - `?search=inventario`
    Respeta la visibilidad (`PUBLICO` vs `FICHA`).
    """

    serializer_class = ProyectoFeedSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = (
            Proyecto.objects.select_related("ficha", "grupo_scrum")
            .prefetch_related("grupo_scrum__miembros__aprendiz", "comentarios")
            .exclude(
                estado__in=[
                    Proyecto.EstadoProyecto.ELIMINADO_POR_GRUPO,
                    Proyecto.EstadoProyecto.RETIRADO_INSTRUCTOR,
                ]
            )
        )

        # Regla de visibilidad: Un aprendiz ve proyectos PUBLICO o los de su propia Ficha
        if user.rol == RolUsuario.APRENDIZ:
            matricula_activa = user.matriculas.filter(activa=True).first()
            ficha_aprendiz_id = matricula_activa.ficha_id if matricula_activa else None
            if ficha_aprendiz_id:
                qs = qs.filter(
                    Q(visibilidad=Proyecto.Visibilidad.PUBLICO)
                    | Q(ficha_id=ficha_aprendiz_id)
                )
            else:
                qs = qs.filter(visibilidad=Proyecto.Visibilidad.PUBLICO)

        ficha_id = self.request.query_params.get("ficha_id")
        if ficha_id:
            qs = qs.filter(ficha_id=ficha_id)

        ficha_numero = self.request.query_params.get("ficha_numero")
        if ficha_numero:
            qs = qs.filter(ficha__numero__iexact=ficha_numero.strip())

        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado.strip().upper())

        tecnologia = self.request.query_params.get("tecnologia")
        if tecnologia:
            qs = qs.filter(tecnologias__icontains=tecnologia.strip())

        busqueda = self.request.query_params.get("search")
        if busqueda:
            termino = busqueda.strip()
            qs = qs.filter(
                Q(titulo__icontains=termino)
                | Q(introduccion__icontains=termino)
                | Q(grupo_scrum__nombre_grupo__icontains=termino)
                | Q(ficha__numero__icontains=termino)
            )

        return qs


class DetalleProyectoView(APIView):
    """
    GET /api/v1/proyectos/<uuid:proyecto_id>/
    Retorna el detalle completo de un proyecto junto con su bitácora y comentarios.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, proyecto_id):
        proyecto = get_object_or_404(
            Proyecto.objects.select_related("ficha", "grupo_scrum").prefetch_related(
                "grupo_scrum__miembros__aprendiz",
                "historial__realizado_por",
                "comentarios__instructor",
                "comentarios__respondido_por",
            ),
            id=proyecto_id,
        )
        from apps.revisiones.serializers import ComentarioRevisionSerializer

        return Response(
            {
                "proyecto": ProyectoFeedSerializer(proyecto).data,
                "historial": HistorialProyectoSerializer(
                    proyecto.historial.all(), many=True
                ).data,
                "comentarios": ComentarioRevisionSerializer(
                    proyecto.comentarios.all(), many=True
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class EjecutarProyectoSandboxInfoView(APIView):
    """
    GET /api/v1/proyectos/<uuid:proyecto_id>/ejecutar/
    Devuelve la URL aislada del servidor Sandbox y metadatos de seguridad para cargar el iframe bajo demanda.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, proyecto_id):
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        if not proyecto.url_ejecucion_sandbox:
            return Response(
                {
                    "detalle": "Este proyecto aún no tiene una entrega publicada para ejecutar en el Sandbox."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        carpeta = (SANDBOX_ROOT / str(proyecto.id)).resolve()
        archivos = []
        total_bytes = 0
        if carpeta.exists():
            for p in sorted(carpeta.rglob("*")):
                if p.is_file():
                    tam = p.stat().st_size
                    total_bytes += tam
                    rel = str(p.relative_to(carpeta))
                    archivos.append(
                        {
                            "ruta": rel,
                            "tamano_bytes": tam,
                            "url_sandbox": f"/sandbox/{proyecto.id}/{rel}",
                        }
                    )

        return Response(
            {
                "proyecto_id": str(proyecto.id),
                "titulo": proyecto.titulo,
                "numero_entrega_actual": proyecto.numero_entrega_actual,
                "punto_entrada": proyecto.punto_entrada,
                "url_ejecucion_sandbox": proyecto.url_ejecucion_sandbox,
                "sandbox_attributes": "allow-scripts",
                "csp_policy": "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; connect-src 'none';",
                "total_archivos_alojados": len(archivos),
                "tamano_total_kb": round(total_bytes / 1024, 2),
                "archivos_alojados": archivos,
            },
            status=status.HTTP_200_OK,
        )


class ValidarIdeaProyectoView(APIView):
    """
    POST /api/v1/proyectos/validar-idea/
    Permite validar previamente si un título e idea de proyecto son únicos en el SENA
    antes de registrarlos oficialmente.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ValidarIdeaProyectoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        miembro = getattr(request.user, "miembro_grupo_scrum", None)
        excluir_grupo_id = miembro.grupo_id if miembro else None

        similares = buscar_proyectos_similares(
            titulo_propuesto=serializer.validated_data["titulo"],
            idea_propuesta=serializer.validated_data["introduccion"],
            excluir_grupo_id=excluir_grupo_id,
        )
        es_unica = len(similares) == 0
        return Response(
            {
                "es_idea_unica": es_unica,
                "proyectos_similares": similares,
                "mensaje": (
                    "La idea y el título son únicos en el SENA. Tu Grupo Scrum puede registrarlos."
                    if es_unica
                    else "Se encontraron proyectos en el SENA con un título o enfoque similar."
                ),
            },
            status=status.HTTP_200_OK,
        )


class MiGrupoProyectoView(APIView):
    """
    GET / POST / DELETE /api/v1/proyectos/mi-grupo/
    Regla 3 y 4:
    - 1 Grupo Scrum = 1 Solo Proyecto.
    - Mínimo 2 aprendices activos en el Grupo Scrum.
    - Cualquiera de los aprendices activos del Grupo Scrum puede registrar la idea,
      actualizarla o retirar el proyecto.
    - Cada acción queda grabada en `HistorialProyecto` con nombre, documento, acción, fecha y hora.
    """

    permission_classes = [EsAprendizActivo]

    def _obtener_grupo_scrum(self, user):
        miembro = getattr(user, "miembro_grupo_scrum", None)
        return miembro.grupo if miembro else None

    def get(self, request):
        grupo = self._obtener_grupo_scrum(request.user)
        if not grupo:
            return Response(
                {"detalle": "Aún no perteneces a ningún Grupo Scrum."},
                status=status.HTTP_404_NOT_FOUND,
            )
        proyecto = getattr(grupo, "proyecto", None)
        integrantes = [
            {
                "id": str(m.aprendiz.id),
                "nombre_completo": m.aprendiz.nombre_completo,
                "documento": m.aprendiz.documento,
                "correo": m.aprendiz.correo,
                "estado_cuenta": m.aprendiz.estado_cuenta,
            }
            for m in grupo.miembros.select_related("aprendiz").all()
        ]
        if not proyecto:
            return Response(
                {
                    "grupo_scrum": {
                        "id": str(grupo.id),
                        "nombre_grupo": grupo.nombre_grupo,
                        "ficha_numero": grupo.ficha.numero,
                        "integrantes": integrantes,
                    },
                    "proyecto": None,
                    "historial": [],
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {
                "grupo_scrum": {
                    "id": str(grupo.id),
                    "nombre_grupo": grupo.nombre_grupo,
                    "ficha_numero": grupo.ficha.numero,
                    "integrantes": integrantes,
                },
                "proyecto": ProyectoFeedSerializer(proyecto).data,
                "historial": HistorialProyectoSerializer(
                    proyecto.historial.select_related("realizado_por").all(),
                    many=True,
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def post(self, request):
        grupo = self._obtener_grupo_scrum(request.user)
        if not grupo:
            return Response(
                {"detalle": "Debes pertenecer a un Grupo Scrum para registrar el proyecto."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Regla 3.2: Verificar que el Grupo Scrum tenga mínimo 2 aprendices no suspendidos
        activos_en_grupo = (
            grupo.miembros.exclude(
                aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO
            ).count()
        )
        if activos_en_grupo < 2:
            return Response(
                {
                    "detalle": (
                        f"Tu Grupo Scrum '{grupo.nombre_grupo}' tiene actualmente {activos_en_grupo} "
                        "aprendiz activo. La regla SENA exige mínimo 2 aprendices activos por Grupo Scrum. "
                        "Solicita a tu instructor reasignar integrantes al grupo."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RegistrarOActualizarIdeaProyectoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        titulo = " ".join(datos["titulo"].strip().split())
        introduccion = datos["introduccion"].strip()

        # Verificar colisión exacta de título (case-insensitive) con otro grupo
        colision_titulo = (
            Proyecto.objects.filter(titulo__iexact=titulo)
            .exclude(grupo_scrum=grupo)
            .select_related("ficha", "grupo_scrum")
            .first()
        )
        if colision_titulo:
            return Response(
                {
                    "detalle": (
                        f"El título '{titulo}' ya está registrado por "
                        f"'{colision_titulo.grupo_scrum.nombre_grupo}' (Ficha {colision_titulo.ficha.numero}). "
                        "Ningún proyecto en el SENA puede repetir nombre."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar originalidad en PostgreSQL (título + vector 768 dims)
        similares = buscar_proyectos_similares(
            titulo_propuesto=titulo,
            idea_propuesta=introduccion,
            excluir_grupo_id=grupo.id,
        )
        if similares:
            return Response(
                {
                    "detalle": (
                        f"El Agente Guardián detectó que esta idea o título se parece a "
                        f"'{similares[0]['titulo']}' ({similares[0]['grupo_scrum']} - Ficha {similares[0]['ficha']}). "
                        "Ningún proyecto en el SENA puede repetir nombre ni idea."
                    ),
                    "proyectos_similares": similares,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        embedding = generar_embedding_768(f"{titulo} {introduccion}")

        proyecto_existente = getattr(grupo, "proyecto", None)
        nuevo_estado = (
            proyecto_existente.estado
            if (
                proyecto_existente
                and proyecto_existente.estado == Proyecto.EstadoProyecto.PUBLICADO
            )
            else Proyecto.EstadoProyecto.IDEA_APROBADA
        )

        proyecto, creado = Proyecto.objects.update_or_create(
            grupo_scrum=grupo,
            defaults={
                "ficha": grupo.ficha,
                "titulo": titulo,
                "introduccion": introduccion,
                "embedding_idea": embedding,
                "tecnologias": datos.get("tecnologias", []),
                "visibilidad": datos.get(
                    "visibilidad", Proyecto.Visibilidad.FICHA
                ),
                "estado": nuevo_estado,
            },
        )

        HistorialProyecto.objects.create(
            proyecto=proyecto,
            realizado_por=request.user,
            accion=HistorialProyecto.TipoAccion.REGISTRO_IDEA,
            numero_entrega=proyecto.numero_entrega_actual,
            descripcion_cambio=(
                f"Registró la idea única del proyecto '{proyecto.titulo}'"
                if creado
                else f"Actualizó la definición del proyecto '{proyecto.titulo}'"
            ),
        )

        return Response(
            ProyectoFeedSerializer(proyecto).data,
            status=status.HTTP_201_CREATED if creado else status.HTTP_200_OK,
        )

    @transaction.atomic
    def delete(self, request):
        grupo = self._obtener_grupo_scrum(request.user)
        if not grupo or not hasattr(grupo, "proyecto"):
            return Response(
                {"detalle": "Tu Grupo Scrum no tiene un proyecto activo."},
                status=status.HTTP_404_NOT_FOUND,
            )

        proyecto = grupo.proyecto
        motivo = (
            request.data.get("motivo")
            or "Retirado del Feed por decisión del Grupo Scrum."
        )
        # Eliminar archivos alojados en el Sandbox para liberar espacio
        limpiar_almacenamiento_proyecto(proyecto)

        proyecto.estado = Proyecto.EstadoProyecto.ELIMINADO_POR_GRUPO
        proyecto.ruta_codigo_actual = ""
        proyecto.estado_procesamiento_zip = "SIN_SUBIR"
        proyecto.save(
            update_fields=[
                "estado",
                "ruta_codigo_actual",
                "estado_procesamiento_zip",
                "actualizado_en",
            ]
        )

        HistorialProyecto.objects.create(
            proyecto=proyecto,
            realizado_por=request.user,
            accion=HistorialProyecto.TipoAccion.ELIMINO_PROYECTO,
            numero_entrega=proyecto.numero_entrega_actual,
            descripcion_cambio=motivo,
        )
        return Response(
            {
                "mensaje": (
                    "El proyecto ha sido retirado y se liberó el archivo alojado en disco. "
                    "La acción quedó registrada en la bitácora del Grupo Scrum."
                )
            },
            status=status.HTTP_200_OK,
        )


class SubirReemplazarCodigoProyectoView(APIView):
    """
    POST /api/v1/proyectos/mi-grupo/subir-codigo/
    Regla 4.3:
    - Solo se aloja la entrega más reciente (`ruta_codigo_actual`).
    - Cuando alguien del Grupo Scrum sube un nuevo `.zip` (o código HTML), valida primero
      que el paquete funcione, borra el archivo anterior, incrementa `numero_entrega_actual`
      y deja constancia en `HistorialProyecto`.
    """

    permission_classes = [EsAprendizActivo]

    @transaction.atomic
    def post(self, request):
        miembro = getattr(request.user, "miembro_grupo_scrum", None)
        if not miembro or not hasattr(miembro.grupo, "proyecto"):
            return Response(
                {"detalle": "Primero debes registrar la idea del proyecto con tu Grupo Scrum."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ReemplazarCodigoProyectoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        proyecto = miembro.grupo.proyecto
        archivo_zip = request.FILES.get("archivo_zip")
        codigo_html = request.data.get("codigo_html")
        punto_entrada = serializer.validated_data["punto_entrada"].strip()

        try:
            nueva_ruta = validar_y_reemplazar_entrega_unica(
                proyecto=proyecto,
                archivo_zip=archivo_zip,
                codigo_html=codigo_html,
                punto_entrada=punto_entrada,
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nueva_entrega = proyecto.numero_entrega_actual + 1
        proyecto.ruta_codigo_actual = nueva_ruta
        proyecto.punto_entrada = punto_entrada
        proyecto.numero_entrega_actual = nueva_entrega
        proyecto.estado_procesamiento_zip = "LISTO"
        proyecto.ultimo_error_zip = ""
        proyecto.estado = Proyecto.EstadoProyecto.PUBLICADO
        proyecto.save(
            update_fields=[
                "ruta_codigo_actual",
                "punto_entrada",
                "numero_entrega_actual",
                "estado_procesamiento_zip",
                "ultimo_error_zip",
                "estado",
                "actualizado_en",
            ]
        )

        HistorialProyecto.objects.create(
            proyecto=proyecto,
            realizado_por=request.user,
            accion=HistorialProyecto.TipoAccion.SUBIO_CODIGO,
            numero_entrega=nueva_entrega,
            descripcion_cambio=serializer.validated_data["descripcion_cambio"],
        )

        return Response(
            {
                "mensaje": (
                    f"Entrega #{nueva_entrega} validada y publicada exitosamente. "
                    "La versión anterior fue eliminada y reemplazada en el almacenamiento."
                ),
                "proyecto": ProyectoFeedSerializer(proyecto).data,
            },
            status=status.HTTP_200_OK,
        )


class RetirarProyectoInstructorView(APIView):
    """
    POST /api/v1/proyectos/<uuid:proyecto_id>/retirar-instructor/
    Permite a un Instructor o Administrador retirar un proyecto del Feed por moderación
    o incumplimiento académico, liberando el archivo en disco y dejando constancia en la bitácora.
    """

    permission_classes = [EsInstructorOAdmin]

    @transaction.atomic
    def post(self, request, proyecto_id):
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        serializer = RetirarProyectoInstructorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motivo = serializer.validated_data["motivo"].strip()

        limpiar_almacenamiento_proyecto(proyecto)
        proyecto.estado = Proyecto.EstadoProyecto.RETIRADO_INSTRUCTOR
        proyecto.ruta_codigo_actual = ""
        proyecto.estado_procesamiento_zip = "SIN_SUBIR"
        proyecto.save(
            update_fields=[
                "estado",
                "ruta_codigo_actual",
                "estado_procesamiento_zip",
                "actualizado_en",
            ]
        )

        HistorialProyecto.objects.create(
            proyecto=proyecto,
            realizado_por=request.user,
            accion=HistorialProyecto.TipoAccion.CAMBIO_ESTADO,
            numero_entrega=proyecto.numero_entrega_actual,
            descripcion_cambio=f"[Retirado por Instructor] {motivo}",
        )

        return Response(
            {
                "mensaje": "El proyecto ha sido retirado por el instructor y se liberó su espacio en disco.",
                "proyecto": ProyectoFeedSerializer(proyecto).data,
            },
            status=status.HTTP_200_OK,
        )


class HistorialBitacoraProyectoView(generics.ListAPIView):
    """
    GET /api/v1/proyectos/<uuid:proyecto_id>/historial/
    Consulta la bitácora inmutable de acciones realizadas por los miembros del Grupo Scrum.
    """

    serializer_class = HistorialProyectoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        proyecto = get_object_or_404(Proyecto, id=self.kwargs["proyecto_id"])
        return proyecto.historial.select_related("realizado_por").all()


class ObtenerUrlSubidaFirmadaProyectoView(APIView):
    """
    POST /api/v1/proyectos/<uuid:proyecto_id>/url-subida/
    Genera una URL firmada (Presigned URL de MinIO/S3 o endpoint local de Sandbox)
    para que cualquier aprendiz activo del Grupo Scrum suba el nuevo .zip que reemplazará al anterior.
    """

    permission_classes = [EsAprendizActivo]

    def post(self, request, proyecto_id):
        from .storage import generar_url_firmada_subida_zip

        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        miembro = getattr(request.user, "miembro_grupo_scrum", None)
        if not miembro or miembro.grupo_id != proyecto.grupo_scrum_id:
            return Response(
                {"detalle": "Solo los miembros activos del Grupo Scrum pueden subir entregas a este proyecto."},
                status=status.HTTP_403_FORBIDDEN,
            )

        nombre_archivo = request.data.get("nombre_archivo", "entrega_actual.zip")
        datos_url = generar_url_firmada_subida_zip(
            proyecto_id=str(proyecto.id),
            nombre_archivo=nombre_archivo,
        )
        return Response(datos_url, status=status.HTTP_200_OK)


class ConfirmarSubidaProyectoView(APIView):
    """
    POST /api/v1/proyectos/<uuid:proyecto_id>/confirmar-subida/
    Valida la entrega, borra el archivo anterior de S3/MinIO y Sandbox, publica el nuevo
    y registra la acción en `HistorialProyecto`.
    """

    permission_classes = [EsAprendizActivo]

    @transaction.atomic
    def post(self, request, proyecto_id):
        from .tasks import validar_y_publicar_entrega_task

        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        miembro = getattr(request.user, "miembro_grupo_scrum", None)
        if not miembro or miembro.grupo_id != proyecto.grupo_scrum_id:
            return Response(
                {"detalle": "Solo los miembros activos del Grupo Scrum pueden confirmar entregas de este proyecto."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ReemplazarCodigoProyectoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        archivo_zip = request.FILES.get("archivo_zip")
        codigo_html = request.data.get("codigo_html")
        punto_entrada = serializer.validated_data["punto_entrada"].strip()
        descripcion_cambio = serializer.validated_data["descripcion_cambio"].strip()

        if archivo_zip:
            try:
                from .storage import eliminar_version_anterior_minio

                eliminar_version_anterior_minio(str(proyecto.id))
                nueva_ruta = validar_y_reemplazar_entrega_unica(
                    proyecto=proyecto,
                    archivo_zip=archivo_zip,
                    codigo_html=codigo_html,
                    punto_entrada=punto_entrada,
                )
            except DjangoValidationError as exc:
                return Response(
                    {"detalle": exc.messages[0]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            nueva_entrega = proyecto.numero_entrega_actual + 1
            proyecto.ruta_codigo_actual = nueva_ruta
            proyecto.punto_entrada = punto_entrada
            proyecto.numero_entrega_actual = nueva_entrega
            proyecto.estado_procesamiento_zip = "LISTO"
            proyecto.ultimo_error_zip = ""
            proyecto.estado = Proyecto.EstadoProyecto.PUBLICADO
            proyecto.save()

            HistorialProyecto.objects.create(
                proyecto=proyecto,
                realizado_por=request.user,
                accion=HistorialProyecto.TipoAccion.SUBIO_CODIGO,
                numero_entrega=nueva_entrega,
                descripcion_cambio=descripcion_cambio,
            )
        else:
            validar_y_publicar_entrega_task(
                proyecto_id=str(proyecto.id),
                usuario_id=str(request.user.id),
                descripcion_cambio=descripcion_cambio,
                punto_entrada=punto_entrada,
                codigo_html=codigo_html,
            )
            proyecto.refresh_from_db()

        return Response(
            {
                "mensaje": (
                    f"Entrega #{proyecto.numero_entrega_actual} confirmada y publicada exitosamente. "
                    "La versión anterior fue eliminada de S3/Sandbox."
                ),
                "proyecto": ProyectoFeedSerializer(proyecto).data,
            },
            status=status.HTTP_200_OK,
        )
