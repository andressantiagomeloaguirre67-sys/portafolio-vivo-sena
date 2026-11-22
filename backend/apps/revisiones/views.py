from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fichas.models import Ficha
from apps.proyectos.models import HistorialProyecto, Proyecto
from apps.proyectos.services import limpiar_almacenamiento_proyecto
from apps.usuarios.models import EstadoCuenta, RolUsuario
from apps.usuarios.permissions import EsAprendizActivo, EsInstructorOAdmin
from .models import ComentarioRevision, Reporte
from .serializers import (
    ComentarioRevisionSerializer,
    CrearComentarioInstructorSerializer,
    CrearReporteSerializer,
    ReporteSerializer,
    ResolverReporteSerializer,
    ResponderComentarioGrupoSerializer,
)


class ComentariosProyectoListCreateView(APIView):
    """
    GET /api/v1/revisiones/proyectos/<uuid:proyecto_id>/comentarios/
    POST /api/v1/revisiones/proyectos/<uuid:proyecto_id>/comentarios/
    Permite ver el hilo completo de comentarios del instructor y respuestas del grupo,
    y que el instructor agregue un nuevo comentario sobre la entrega actual.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [EsInstructorOAdmin()]
        return [IsAuthenticated()]

    def get(self, request, proyecto_id):
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        comentarios = proyecto.comentarios.select_related(
            "instructor", "respondido_por"
        ).all()
        return Response(
            ComentarioRevisionSerializer(comentarios, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request, proyecto_id):
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        serializer = CrearComentarioInstructorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comentario = ComentarioRevision.objects.create(
            proyecto=proyecto,
            instructor=request.user,
            numero_entrega_revisada=max(proyecto.numero_entrega_actual, 1),
            comentario_instructor=serializer.validated_data["comentario_instructor"],
        )
        return Response(
            ComentarioRevisionSerializer(comentario).data,
            status=status.HTTP_201_CREATED,
        )


class ResponderComentarioGrupoView(APIView):
    """
    POST /api/v1/revisiones/comentarios/<uuid:comentario_id>/responder/
    Regla 4.2 y 4.4: Cualquier aprendiz activo del Grupo Scrum del proyecto puede responder
    al comentario del instructor dejando constancia de la entrega corregida y registrando
    la acción en `HistorialProyecto`.
    """

    permission_classes = [EsAprendizActivo]

    @transaction.atomic
    def post(self, request, comentario_id):
        comentario = get_object_or_404(
            ComentarioRevision.objects.select_related("proyecto__grupo_scrum"),
            id=comentario_id,
        )
        miembro = getattr(request.user, "miembro_grupo_scrum", None)
        if not miembro or miembro.grupo_id != comentario.proyecto.grupo_scrum_id:
            return Response(
                {
                    "detalle": "Solo los integrantes del Grupo Scrum del proyecto pueden responder este comentario."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ResponderComentarioGrupoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        respuesta_texto = serializer.validated_data["respuesta_grupo"].strip()
        comentario.respuesta_grupo = respuesta_texto
        comentario.respondido_por = request.user
        comentario.fecha_respuesta = timezone.now()
        comentario.corregido_en_entrega = comentario.proyecto.numero_entrega_actual
        comentario.save(
            update_fields=[
                "respuesta_grupo",
                "respondido_por",
                "fecha_respuesta",
                "corregido_en_entrega",
            ]
        )

        # Regla 4.2: Registrar también en la bitácora HistorialProyecto
        HistorialProyecto.objects.create(
            proyecto=comentario.proyecto,
            realizado_por=request.user,
            accion=HistorialProyecto.TipoAccion.RESPUESTA_COMENTARIO,
            numero_entrega=comentario.proyecto.numero_entrega_actual,
            descripcion_cambio=f"Respondió al comentario de revisión: '{respuesta_texto[:120]}'",
        )

        return Response(
            ComentarioRevisionSerializer(comentario).data,
            status=status.HTTP_200_OK,
        )


class ReportesProyectoListCreateView(APIView):
    """
    GET / POST /api/v1/revisiones/reportes/
    Permite a cualquier usuario autenticado reportar un proyecto y a los Instructores/Admin
    listar los reportes de moderación.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.rol not in (RolUsuario.INSTRUCTOR, RolUsuario.ADMIN):
            reportes = Reporte.objects.filter(
                reportado_por=request.user
            ).select_related("proyecto", "reportado_por", "resuelto_por")
        else:
            reportes = Reporte.objects.select_related(
                "proyecto", "reportado_por", "resuelto_por"
            ).all()
        return Response(
            ReporteSerializer(reportes, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = CrearReporteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        proyecto = get_object_or_404(
            Proyecto, id=serializer.validated_data["proyecto"]
        )
        reporte = Reporte.objects.create(
            proyecto=proyecto,
            reportado_por=request.user,
            motivo=serializer.validated_data["motivo"].strip(),
        )
        return Response(
            ReporteSerializer(reporte).data,
            status=status.HTTP_201_CREATED,
        )


class ResolverReporteProyectoView(APIView):
    """
    POST /api/v1/revisiones/reportes/<uuid:reporte_id>/resolver/
    Permite al Instructor o Administrador resolver un reporte:
    - Si decide `PROYECTO_RETIRADO`, retira el proyecto del Feed, libera el archivo en disco
      y deja constancia en `HistorialProyecto`.
    - Si decide `DESCARTADO`, cierra el reporte manteniendo el proyecto activo.
    """

    permission_classes = [EsInstructorOAdmin]

    @transaction.atomic
    def post(self, request, reporte_id):
        reporte = get_object_or_404(
            Reporte.objects.select_related("proyecto"), id=reporte_id
        )
        serializer = ResolverReporteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = serializer.validated_data["decision"]
        nota = serializer.validated_data["nota_resolucion"].strip()

        reporte.estado = decision
        reporte.nota_resolucion = nota
        reporte.resuelto_por = request.user
        reporte.resuelto_en = timezone.now()
        reporte.save(
            update_fields=["estado", "nota_resolucion", "resuelto_por", "resuelto_en"]
        )

        if decision == Reporte.EstadoReporte.PROYECTO_RETIRADO:
            proyecto = reporte.proyecto
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
                descripcion_cambio=f"[Reporte Moderación Aceptado] {nota}",
            )

        return Response(
            ReporteSerializer(reporte).data,
            status=status.HTTP_200_OK,
        )


class ResumenDashboardInstructorView(APIView):
    """
    GET /api/v1/revisiones/resumen-instructor/
    Entrega un tablero consolidado para el Instructor o Administrador con métricas
    en tiempo real de sus fichas asignadas, Grupos Scrum, proyectos y aprendices.
    """

    permission_classes = [EsInstructorOAdmin]

    def get(self, request):
        user = request.user
        if user.rol == RolUsuario.INSTRUCTOR:
            fichas = Ficha.objects.filter(
                asignaciones__instructor=user,
                asignaciones__activa=True,
            ).distinct()
        else:
            fichas = Ficha.objects.filter(activa=True)

        proyectos_qs = Proyecto.objects.filter(ficha__in=fichas)
        reportes_pendientes = Reporte.objects.filter(
            proyecto__ficha__in=fichas,
            estado=Reporte.EstadoReporte.PENDIENTE,
        ).count()

        resumen_fichas = []
        for f in fichas:
            total_grupos = f.grupos_scrum.count()
            publicados = f.proyectos.filter(
                estado=Proyecto.EstadoProyecto.PUBLICADO
            ).count()
            activos = (
                f.matriculas.filter(activa=True)
                .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
                .count()
            )
            suspendidos = f.matriculas.filter(
                activa=True, aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO
            ).count()
            resumen_fichas.append(
                {
                    "ficha_id": str(f.id),
                    "numero": f.numero,
                    "programa": f.programa,
                    "jornada": f.jornada,
                    "grupos_scrum": total_grupos,
                    "proyectos_publicados": publicados,
                    "aprendices_activos": activos,
                    "aprendices_suspendidos": suspendidos,
                }
            )

        return Response(
            {
                "total_fichas_asignadas": fichas.count(),
                "total_proyectos_publicados": proyectos_qs.filter(
                    estado=Proyecto.EstadoProyecto.PUBLICADO
                ).count(),
                "total_ideas_aprobadas_sin_codigo": proyectos_qs.filter(
                    estado=Proyecto.EstadoProyecto.IDEA_APROBADA
                ).count(),
                "reportes_moderacion_pendientes": reportes_pendientes,
                "fichas": resumen_fichas,
            },
            status=status.HTTP_200_OK,
        )


class BuscadorGlobalInstructorView(APIView):
    """
    GET /api/v1/revisiones/buscador-instructor/?q=<termino>&ficha_id=<opcional>
    Buscador unificado para el Instructor y Administrador:
    Busca simultáneamente Aprendices (por documento, nombre, correo o estado),
    Grupos Scrum (por nombre o ficha) y Proyectos (por título, introducción o tecnología).
    """

    permission_classes = [EsInstructorOAdmin]

    def get(self, request):
        from django.db.models import Q
        from apps.fichas.models import GrupoScrum
        from apps.fichas.serializers import GrupoScrumSerializer
        from apps.proyectos.serializers import ProyectoFeedSerializer
        from apps.usuarios.models import Usuario
        from apps.usuarios.serializers import UsuarioPerfilSerializer

        q = (request.query_params.get("q") or "").strip()
        ficha_id = (request.query_params.get("ficha_id") or "").strip()

        aprendices_qs = (
            Usuario.objects.filter(rol=RolUsuario.APRENDIZ)
            .select_related("suspendido_por")
            .prefetch_related("membresias_grupo_scrum__grupo")
        )
        grupos_qs = (
            GrupoScrum.objects.exclude(estado=GrupoScrum.EstadoGrupo.ARCHIVADO)
            .select_related("ficha", "proyecto")
            .prefetch_related("miembros__aprendiz")
        )
        proyectos_qs = Proyecto.objects.select_related("ficha", "grupo_scrum").prefetch_related(
            "grupo_scrum__miembros__aprendiz", "comentarios"
        )

        if ficha_id:
            aprendices_qs = aprendices_qs.filter(matriculas__ficha_id=ficha_id, matriculas__activa=True)
            grupos_qs = grupos_qs.filter(ficha_id=ficha_id)
            proyectos_qs = proyectos_qs.filter(ficha_id=ficha_id)

        if q:
            aprendices_qs = aprendices_qs.filter(
                Q(documento__icontains=q)
                | Q(nombre_completo__icontains=q)
                | Q(correo__icontains=q)
                | Q(estado_cuenta__icontains=q)
                | Q(
                    membresias_grupo_scrum__activo=True,
                    membresias_grupo_scrum__grupo__nombre_grupo__icontains=q,
                )
            ).distinct()
            grupos_qs = grupos_qs.filter(
                Q(nombre_grupo__icontains=q)
                | Q(ficha__numero__icontains=q)
                | Q(miembros__aprendiz__nombre_completo__icontains=q)
                | Q(miembros__aprendiz__documento__icontains=q)
            ).distinct()
            proyectos_qs = proyectos_qs.filter(
                Q(titulo__icontains=q)
                | Q(introduccion__icontains=q)
                | Q(grupo_scrum__nombre_grupo__icontains=q)
                | Q(ficha__numero__icontains=q)
                | Q(tecnologias__icontains=q)
            )

        return Response(
            {
                "termino": q,
                "aprendices": UsuarioPerfilSerializer(aprendices_qs[:25], many=True).data,
                "grupos_scrum": GrupoScrumSerializer(grupos_qs[:20], many=True).data,
                "proyectos": ProyectoFeedSerializer(proyectos_qs[:20], many=True).data,
            },
            status=status.HTTP_200_OK,
        )
