from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario
from apps.usuarios.permissions import EsInstructorOAdmin
from apps.usuarios.serializers import UsuarioPerfilSerializer
from .models import AsignacionInstructor, CargaMasiva, Ficha, GrupoScrum
from .serializers import (
    AsignacionInstructorSerializer,
    CargaMasivaFichaRequestSerializer,
    CargaMasivaSerializer,
    ConformarGrupoScrumSerializer,
    FichaSerializer,
    GrupoScrumSerializer,
    RotarInstructorSerializer,
)
from .services import (
    conformar_o_reasignar_grupo_scrum,
    disolver_grupo_scrum,
    extraer_registros_desde_archivo,
    procesar_carga_masiva_ficha,
    rotar_instructor_ficha,
)


class FichaListCreateView(generics.ListCreateAPIView):
    """
    GET /api/v1/fichas/ -> Lista las fichas (permite filtrar con `?mis_fichas=true` para el instructor).
    POST /api/v1/fichas/ -> Crea una nueva ficha (y asigna al instructor actual o `instructor_id` indicado).
    """

    serializer_class = FichaSerializer

    def get_queryset(self):
        qs = Ficha.objects.prefetch_related("asignaciones__instructor").all()
        if self.request.query_params.get("mis_fichas") == "true" and self.request.user.rol == RolUsuario.INSTRUCTOR:
            qs = qs.filter(
                asignaciones__instructor=self.request.user,
                asignaciones__activa=True,
            )
        return qs

    def get_permissions(self):
        if self.request.method == "POST":
            return [EsInstructorOAdmin()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        ficha = serializer.save()
        trimestre = self.request.data.get("trimestre", "2026-Trimestre-3")
        instructor_id = self.request.data.get("instructor_id")

        instructor_asignar = None
        if instructor_id:
            instructor_asignar = Usuario.objects.filter(
                id=instructor_id, rol=RolUsuario.INSTRUCTOR, is_active=True
            ).first()
        elif self.request.user.rol == RolUsuario.INSTRUCTOR:
            instructor_asignar = self.request.user

        if instructor_asignar:
            rotar_instructor_ficha(
                ficha=ficha,
                nuevo_instructor=instructor_asignar,
                trimestre=trimestre,
            )


class FichaDetailView(generics.RetrieveUpdateAPIView):
    """
    GET / PATCH / PUT /api/v1/fichas/<uuid:ficha_id>/
    Obtiene o actualiza los datos de una ficha específica.
    """

    queryset = Ficha.objects.all()
    serializer_class = FichaSerializer
    lookup_url_kwarg = "ficha_id"

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [EsInstructorOAdmin()]
        return [IsAuthenticated()]


class HistorialInstructoresFichaView(generics.ListAPIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/historial-instructores/
    Regla 2: Muestra el historial de rotación trimestral de instructores de la ficha,
    destacando quién está activo en el trimestre actual y quiénes estuvieron antes.
    """

    serializer_class = AsignacionInstructorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            AsignacionInstructor.objects.filter(ficha_id=self.kwargs["ficha_id"])
            .select_related("instructor", "ficha")
            .order_by("-activa", "-fecha_inicio")
        )


class InstructoresActivosListView(APIView):
    """
    GET /api/v1/fichas/instructores/
    Lista los instructores activos para poder rotar el instructor de una ficha por trimestre.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        instructores = Usuario.objects.filter(
            rol=RolUsuario.INSTRUCTOR, is_active=True
        ).order_by("nombre_completo")
        return Response(
            [
                {
                    "id": str(i.id),
                    "documento": i.documento,
                    "nombre_completo": i.nombre_completo,
                    "correo": i.correo,
                    "fichas_activas": i.fichas_asignadas.filter(activa=True).count(),
                }
                for i in instructores
            ],
            status=status.HTTP_200_OK,
        )


class RotarInstructorFichaView(APIView):
    """
    POST /api/v1/fichas/<uuid:ficha_id>/rotar-instructor/
    Regla 2: Una ficha solo puede tener 1 instructor activo por trimestre.
    Desactiva la asignación anterior (conservando su historial de comentarios)
    y activa al nuevo instructor.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        serializer = RotarInstructorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        nuevo_instructor = get_object_or_404(
            Usuario, id=serializer.validated_data["instructor_id"]
        )
        asignacion = rotar_instructor_ficha(
            ficha=ficha,
            nuevo_instructor=nuevo_instructor,
            trimestre=serializer.validated_data["trimestre"],
        )
        return Response(
            {
                "mensaje": (
                    f"Instructor activo de la ficha {ficha.numero} actualizado a "
                    f"{nuevo_instructor.nombre_completo} ({asignacion.trimestre})."
                ),
                "asignacion": AsignacionInstructorSerializer(asignacion).data,
                "ficha": FichaSerializer(ficha).data,
            },
            status=status.HTTP_200_OK,
        )


class CargaMasivaGruposScrumView(APIView):
    """
    POST /api/v1/fichas/<uuid:ficha_id>/carga-masiva/
    Regla 3:
    - Acepta archivo `.xlsx`/`.csv` (`archivo`) o lista JSON (`registros`).
    - Valida que ningún `documento` ni `nombre_completo` se repita en varios Grupos Scrum.
    - Valida que todo Grupo Scrum tenga mínimo 2 aprendices.
    - Si hay alertas, responde con 400 e informa inmediatamente las personas/grupos afectados.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        archivo_subido = request.FILES.get("archivo")

        if archivo_subido:
            nombre_archivo = archivo_subido.name
            registros = extraer_registros_desde_archivo(archivo_subido)
            if not registros:
                return Response(
                    {"detalle": "El archivo subido está vacío o no tiene formato válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            serializer = CargaMasivaFichaRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            nombre_archivo = serializer.validated_data["nombre_archivo"]
            registros = serializer.validated_data["registros"]

        carga, resultado = procesar_carga_masiva_ficha(
            ficha=ficha,
            instructor=request.user,
            registros=registros,
            nombre_archivo=nombre_archivo,
        )

        if carga.estado == "CON_ALERTAS":
            return Response(
                {
                    "mensaje": (
                        "Alerta de validación: Se detectaron inconsistencias, personas repetidas en varios "
                        "Grupos Scrum o grupos con menos de 2 aprendices."
                    ),
                    "carga": CargaMasivaSerializer(carga).data,
                    "alertas": resultado,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "mensaje": "Carga masiva de aprendices y Grupos Scrum procesada exitosamente.",
                "carga": CargaMasivaSerializer(carga).data,
                "aprendices_procesados": resultado,
            },
            status=status.HTTP_201_CREATED,
        )


class HistorialCargasMasivasFichaView(generics.ListAPIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/cargas-masivas/
    Lista las cargas masivas realizadas sobre una ficha junto con sus alertas registradas.
    """

    serializer_class = CargaMasivaSerializer
    permission_classes = [EsInstructorOAdmin]

    def get_queryset(self):
        return (
            CargaMasiva.objects.filter(ficha_id=self.kwargs["ficha_id"])
            .select_related("instructor", "ficha")
            .order_by("-creado_en")
        )


class GruposScrumFichaListView(generics.ListAPIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/grupos-scrum/
    Lista los Grupos Scrum de una ficha con sus integrantes y proyecto asociado.
    """

    serializer_class = GrupoScrumSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            GrupoScrum.objects.filter(ficha_id=self.kwargs["ficha_id"])
            .prefetch_related("miembros__aprendiz")
            .select_related("proyecto")
        )


class ConformarGrupoScrumView(APIView):
    """
    POST /api/v1/fichas/<uuid:ficha_id>/grupos-scrum/conformar/
    Permite al instructor crear un Grupo Scrum o reasignar aprendices activos de la ficha
    cumpliendo mínimo 2 aprendices activos por grupo y máximo 1 grupo por aprendiz.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        serializer = ConformarGrupoScrumSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            grupo = conformar_o_reasignar_grupo_scrum(
                ficha=ficha,
                nombre_grupo=serializer.validated_data["nombre_grupo"],
                documentos_aprendices=serializer.validated_data["documentos_aprendices"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "mensaje": f"Grupo '{grupo.nombre_grupo}' conformado exitosamente en la ficha {ficha.numero}.",
                "grupo_scrum": GrupoScrumSerializer(grupo).data,
            },
            status=status.HTTP_200_OK,
        )


class AprendicesFichaListView(APIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/aprendices/
    Lista todos los aprendices matriculados en la ficha (activos, pendientes y suspendidos con su motivo).
    Permite al instructor buscar con `?search=` (por documento, nombre, correo o nombre de Grupo Scrum)
    y filtrar con `?estado_cuenta=ACTIVO|PENDIENTE|SUSPENDIDO`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, ficha_id):
        from django.db.models import Q

        ficha = get_object_or_404(Ficha, id=ficha_id)
        matriculas = ficha.matriculas.select_related(
            "aprendiz",
            "aprendiz__suspendido_por",
            "aprendiz__miembro_grupo_scrum__grupo",
        )

        estado_cuenta = (request.query_params.get("estado_cuenta") or "").strip().upper()
        if estado_cuenta:
            matriculas = matriculas.filter(aprendiz__estado_cuenta=estado_cuenta)

        busqueda = (request.query_params.get("search") or "").strip()
        if busqueda:
            matriculas = matriculas.filter(
                Q(aprendiz__documento__icontains=busqueda)
                | Q(aprendiz__nombre_completo__icontains=busqueda)
                | Q(aprendiz__correo__icontains=busqueda)
                | Q(aprendiz__miembro_grupo_scrum__grupo__nombre_grupo__icontains=busqueda)
            )

        matriculas = matriculas.order_by("aprendiz__nombre_completo")
        datos = [
            UsuarioPerfilSerializer(mat.aprendiz).data for mat in matriculas
        ]
        return Response(datos, status=status.HTTP_200_OK)


class DisolverGrupoScrumView(APIView):
    """
    DELETE /api/v1/fichas/grupos-scrum/<uuid:grupo_id>/disolver/
    Regla 3.5: Si un grupo se separa o disuelve, el GrupoScrum SÍ se puede eliminar/disolver
    para reasignar a los aprendices activos, pero los aprendices nunca se eliminan.
    """

    permission_classes = [EsInstructorOAdmin]

    def delete(self, request, grupo_id):
        grupo = get_object_or_404(
            GrupoScrum.objects.select_related("ficha").prefetch_related("miembros__aprendiz"),
            id=grupo_id,
        )
        resultado = disolver_grupo_scrum(grupo)
        return Response(
            {
                "mensaje": (
                    f"El grupo '{resultado['nombre_grupo']}' de la ficha {resultado['ficha_numero']} "
                    "fue disuelto. Los aprendices continúan activos en la ficha para ser reasignados."
                ),
                "aprendices_liberados": resultado["aprendices_liberados"],
            },
            status=status.HTTP_200_OK,
        )


class AprendicesSinProyectoFichaView(APIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/alertas-sin-proyecto/
    Regla 1.4: Lista los aprendices ACTIVOS o PENDIENTES (excluyendo SUSPENDIDOS) de la ficha
    que aún no tienen Grupo Scrum o cuyo Grupo Scrum no tiene proyecto publicado,
    además de alertar sobre Grupos Scrum que hayan quedado con menos de 2 aprendices activos.
    """

    permission_classes = [EsInstructorOAdmin]

    def get(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        matriculas_no_suspendidas = (
            ficha.matriculas.filter(activa=True)
            .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
            .select_related("aprendiz", "aprendiz__miembro_grupo_scrum__grupo")
        )

        sin_grupo = []
        sin_proyecto = []
        for mat in matriculas_no_suspendidas:
            aprendiz = mat.aprendiz
            miembro = getattr(aprendiz, "miembro_grupo_scrum", None)
            if not miembro:
                sin_grupo.append(
                    {
                        "id": str(aprendiz.id),
                        "documento": aprendiz.documento,
                        "nombre_completo": aprendiz.nombre_completo,
                        "estado_cuenta": aprendiz.estado_cuenta,
                    }
                )
            else:
                proyecto = getattr(miembro.grupo, "proyecto", None)
                if not proyecto or proyecto.estado in (
                    "ELIMINADO_POR_GRUPO",
                    "RETIRADO_INSTRUCTOR",
                ):
                    sin_proyecto.append(
                        {
                            "id": str(aprendiz.id),
                            "documento": aprendiz.documento,
                            "nombre_completo": aprendiz.nombre_completo,
                            "grupo_scrum": miembro.grupo.nombre_grupo,
                        }
                    )

        grupos_incompletos = []
        for grupo in ficha.grupos_scrum.prefetch_related("miembros__aprendiz").all():
            activos = [
                m.aprendiz
                for m in grupo.miembros.all()
                if m.aprendiz.estado_cuenta != EstadoCuenta.SUSPENDIDO
            ]
            if len(activos) < 2:
                grupos_incompletos.append(
                    {
                        "grupo_id": str(grupo.id),
                        "nombre_grupo": grupo.nombre_grupo,
                        "cantidad_aprendices_activos": len(activos),
                        "mensaje": (
                            f"El grupo '{grupo.nombre_grupo}' tiene {len(activos)} aprendiz(ces) "
                            "no suspendidos (mínimo requerido: 2)."
                        ),
                    }
                )

        return Response(
            {
                "ficha": ficha.numero,
                "aprendices_sin_grupo_scrum": sin_grupo,
                "aprendices_en_grupo_sin_proyecto": sin_proyecto,
                "grupos_con_menos_de_dos_activos": grupos_incompletos,
            },
            status=status.HTTP_200_OK,
        )
