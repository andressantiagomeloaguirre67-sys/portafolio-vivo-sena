from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.usuarios.models import EstadoCuenta, RolUsuario, Usuario
from apps.usuarios.permissions import EsInstructorOAdmin
from apps.usuarios.serializers import UsuarioPerfilSerializer
from .models import AsignacionInstructor, Ficha, GrupoScrum, MiembroGrupoScrum
from .serializers import (
    AgregarIntegranteEquipoSerializer,
    AsignacionInstructorSerializer,
    CambiarEstadoEquipoSerializer,
    CambiarRolIntegranteSerializer,
    CrearEquipoScrumSerializer,
    FichaSerializer,
    GrupoScrumSerializer,
    MoverIntegranteEquipoSerializer,
    RegistrarAprendizIndividualSerializer,
    RotarInstructorSerializer,
)
from .services import (
    agregar_integrante_a_equipo,
    archivar_equipo_scrum,
    cambiar_estado_equipo_scrum,
    cambiar_rol_integrante_equipo,
    crear_equipo_scrum,
    mover_integrante_de_equipo,
    registrar_e_invitar_aprendiz_individual,
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
    Regla 2: Muestra el historial de rotación trimestral de instructores de la ficha.
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
    Lista los instructores activos para rotación trimestral.
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


class GruposScrumFichaListView(APIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/grupos-scrum/
    Lista los Equipos Scrum de la ficha (soporta `?estado=BORRADOR|PUBLICADO|ARCHIVADO|TODOS`).

    POST /api/v1/fichas/<uuid:ficha_id>/grupos-scrum/
    Crea un nuevo Equipo Scrum directamente seleccionando aprendices activos sin equipo
    de la ficha, con proyecto asociado, roles Scrum opcionales y estado inicial (Borrador/Publicado).
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [EsInstructorOAdmin()]
        return [IsAuthenticated()]

    def get(self, request, ficha_id):
        get_object_or_404(Ficha, id=ficha_id)
        qs = (
            GrupoScrum.objects.filter(ficha_id=ficha_id)
            .prefetch_related("miembros__aprendiz")
            .select_related("proyecto")
        )
        estado = (request.query_params.get("estado") or "").strip().upper()
        if estado in (
            GrupoScrum.EstadoGrupo.BORRADOR,
            GrupoScrum.EstadoGrupo.PUBLICADO,
            GrupoScrum.EstadoGrupo.ARCHIVADO,
        ):
            qs = qs.filter(estado=estado)
        elif estado != "TODOS":
            qs = qs.exclude(estado=GrupoScrum.EstadoGrupo.ARCHIVADO)

        return Response(GrupoScrumSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    def post(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        serializer = CrearEquipoScrumSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data

        try:
            grupo = crear_equipo_scrum(
                ficha=ficha,
                nombre_grupo=datos["nombre_grupo"],
                proyecto_titulo=datos["proyecto_titulo"],
                proyecto_descripcion=datos["proyecto_descripcion"],
                integrantes=datos["integrantes"],
                estado=datos.get("estado", GrupoScrum.EstadoGrupo.BORRADOR),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        grupo = (
            GrupoScrum.objects.select_related("proyecto")
            .prefetch_related("miembros__aprendiz")
            .get(id=grupo.id)
        )
        etiqueta_estado = "publicado" if grupo.estado == GrupoScrum.EstadoGrupo.PUBLICADO else "guardado como borrador"
        return Response(
            {
                "mensaje": f"Equipo '{grupo.nombre_grupo}' {etiqueta_estado} exitosamente.",
                "grupo_scrum": GrupoScrumSerializer(grupo).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CambiarEstadoGrupoScrumView(APIView):
    """
    PATCH /api/v1/fichas/grupos-scrum/<uuid:grupo_id>/estado/
    Cambia el estado de un equipo entre BORRADOR y PUBLICADO.
    """

    permission_classes = [EsInstructorOAdmin]

    def patch(self, request, grupo_id):
        grupo = get_object_or_404(GrupoScrum, id=grupo_id)
        serializer = CambiarEstadoEquipoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            grupo = cambiar_estado_equipo_scrum(
                grupo=grupo,
                nuevo_estado=serializer.validated_data["estado"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        grupo = (
            GrupoScrum.objects.select_related("proyecto")
            .prefetch_related("miembros__aprendiz")
            .get(id=grupo.id)
        )
        etiqueta = "Publicado" if grupo.estado == GrupoScrum.EstadoGrupo.PUBLICADO else "Borrador"
        return Response(
            {
                "mensaje": f"El equipo '{grupo.nombre_grupo}' ahora está en estado {etiqueta}.",
                "grupo_scrum": GrupoScrumSerializer(grupo).data,
            },
            status=status.HTTP_200_OK,
        )


class ArchivarGrupoScrumView(APIView):
    """
    POST /api/v1/fichas/grupos-scrum/<uuid:grupo_id>/archivar/
    Regla No-Delete: archiva el equipo en lugar de eliminarlo físicamente,
    cierra sus membresías activas y libera a sus aprendices para otros equipos.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, grupo_id):
        grupo = get_object_or_404(GrupoScrum, id=grupo_id)
        try:
            resultado = archivar_equipo_scrum(grupo)
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "mensaje": (
                    f"El equipo '{resultado['nombre_grupo']}' fue archivado sin borrar su historial. "
                    "Sus integrantes quedaron disponibles para asignarse a otro equipo."
                ),
                **resultado,
            },
            status=status.HTTP_200_OK,
        )


class IntegrantesGrupoScrumView(APIView):
    """
    POST /api/v1/fichas/grupos-scrum/<uuid:grupo_id>/integrantes/
    Agrega un aprendiz activo sin equipo de la misma ficha al grupo.

    PATCH /api/v1/fichas/grupos-scrum/<uuid:grupo_id>/integrantes/
    Actualiza el rol Scrum de un integrante activo del grupo.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, grupo_id):
        grupo = get_object_or_404(GrupoScrum, id=grupo_id)
        serializer = AgregarIntegranteEquipoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            membresia = agregar_integrante_a_equipo(
                grupo=grupo,
                aprendiz_id=serializer.validated_data["aprendiz_id"],
                rol_scrum=serializer.validated_data.get(
                    "rol_scrum", MiembroGrupoScrum.RolScrum.DEVELOPER
                ),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        grupo = (
            GrupoScrum.objects.select_related("proyecto")
            .prefetch_related("miembros__aprendiz")
            .get(id=grupo.id)
        )
        return Response(
            {
                "mensaje": f"{membresia.aprendiz.nombre_completo} se agregó al equipo '{grupo.nombre_grupo}'.",
                "grupo_scrum": GrupoScrumSerializer(grupo).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, grupo_id):
        grupo = get_object_or_404(GrupoScrum, id=grupo_id)
        serializer = CambiarRolIntegranteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            membresia = cambiar_rol_integrante_equipo(
                grupo=grupo,
                aprendiz_id=serializer.validated_data["aprendiz_id"],
                rol_scrum=serializer.validated_data["rol_scrum"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        grupo = (
            GrupoScrum.objects.select_related("proyecto")
            .prefetch_related("miembros__aprendiz")
            .get(id=grupo.id)
        )
        return Response(
            {
                "mensaje": f"Rol de {membresia.aprendiz.nombre_completo} actualizado.",
                "grupo_scrum": GrupoScrumSerializer(grupo).data,
            },
            status=status.HTTP_200_OK,
        )


class MoverIntegranteGrupoScrumView(APIView):
    """
    POST /api/v1/fichas/grupos-scrum/<uuid:grupo_id>/mover-integrante/
    Mueve un aprendiz desde `grupo_id` hacia `grupo_destino_id` cerrando su membresía previa
    con `fecha_fin` y abriendo la nueva sin borrar historial.
    """

    permission_classes = [EsInstructorOAdmin]

    def post(self, request, grupo_id):
        grupo_origen = get_object_or_404(GrupoScrum, id=grupo_id)
        serializer = MoverIntegranteEquipoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            nueva_membresia = mover_integrante_de_equipo(
                grupo_origen=grupo_origen,
                aprendiz_id=serializer.validated_data["aprendiz_id"],
                grupo_destino_id=serializer.validated_data["grupo_destino_id"],
                rol_scrum=serializer.validated_data.get(
                    "rol_scrum", MiembroGrupoScrum.RolScrum.DEVELOPER
                ),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        grupo_actualizado = (
            GrupoScrum.objects.select_related("proyecto")
            .prefetch_related("miembros__aprendiz")
            .get(id=grupo_origen.id)
        )
        return Response(
            {
                "mensaje": (
                    f"{nueva_membresia.aprendiz.nombre_completo} fue movido al equipo "
                    f"'{nueva_membresia.grupo.nombre_grupo}' conservando su historial."
                ),
                "grupo_scrum": GrupoScrumSerializer(grupo_actualizado).data,
            },
            status=status.HTTP_200_OK,
        )


class AprendicesFichaListView(APIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/aprendices/
    Lista los aprendices matriculados en la ficha con filtros:
    - `?search=` (documento, nombre, correo o nombre de equipo activo)
    - `?estado_cuenta=ACTIVO|PENDIENTE|SUSPENDIDO`
    - `?sin_equipo=true` (solo aprendices sin membresía activa en la ficha)

    POST /api/v1/fichas/<uuid:ficha_id>/aprendices/
    Registra e invita por correo a un aprendiz individual en la ficha.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [EsInstructorOAdmin()]
        return [IsAuthenticated()]

    def get(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        membresia_activa_subq = MiembroGrupoScrum.objects.filter(
            ficha=ficha,
            aprendiz_id=OuterRef("aprendiz_id"),
            activo=True,
        )
        matriculas = (
            ficha.matriculas.filter(activa=True)
            .select_related("aprendiz", "aprendiz__suspendido_por")
            .prefetch_related("aprendiz__membresias_grupo_scrum__grupo")
            .annotate(tiene_equipo_activo=Exists(membresia_activa_subq))
        )

        estado_cuenta = (request.query_params.get("estado_cuenta") or "").strip().upper()
        if estado_cuenta:
            matriculas = matriculas.filter(aprendiz__estado_cuenta=estado_cuenta)

        sin_equipo = (request.query_params.get("sin_equipo") or "").strip().lower()
        if sin_equipo in ("true", "1", "si"):
            matriculas = matriculas.filter(tiene_equipo_activo=False).exclude(
                aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO
            )

        busqueda = (request.query_params.get("search") or "").strip()
        if busqueda:
            matriculas = matriculas.filter(
                Q(aprendiz__documento__icontains=busqueda)
                | Q(aprendiz__nombre_completo__icontains=busqueda)
                | Q(aprendiz__correo__icontains=busqueda)
                | Q(
                    aprendiz__membresias_grupo_scrum__activo=True,
                    aprendiz__membresias_grupo_scrum__grupo__nombre_grupo__icontains=busqueda,
                )
            ).distinct()

        matriculas = matriculas.order_by("aprendiz__nombre_completo")
        datos = [UsuarioPerfilSerializer(mat.aprendiz).data for mat in matriculas]
        return Response(datos, status=status.HTTP_200_OK)

    def post(self, request, ficha_id):
        from django.conf import settings

        ficha = get_object_or_404(Ficha, id=ficha_id)
        serializer = RegistrarAprendizIndividualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            aprendiz, creado, correo_enviado = registrar_e_invitar_aprendiz_individual(
                ficha=ficha,
                nombre_completo=serializer.validated_data["nombre_completo"],
                documento=serializer.validated_data["documento"],
                correo=serializer.validated_data["correo"],
                grupo_scrum=serializer.validated_data.get("grupo_scrum", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detalle": exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if aprendiz.estado_cuenta == EstadoCuenta.PENDIENTE:
            mensaje = (
                f"Aprendiz {aprendiz.nombre_completo} registrado en la ficha {ficha.numero} "
                f"e invitación enviada a {aprendiz.correo}."
            )
        else:
            mensaje = (
                f"Aprendiz {aprendiz.nombre_completo} vinculado a la ficha {ficha.numero} "
                "(su cuenta ya estaba activa)."
            )

        payload = {
            "mensaje": mensaje,
            "aprendiz": UsuarioPerfilSerializer(aprendiz).data,
            "creado": creado,
            "correo_enviado": correo_enviado,
        }
        if settings.DEBUG and aprendiz.token_activacion:
            payload["token_activacion_dev"] = aprendiz.token_activacion

        return Response(
            payload,
            status=status.HTTP_201_CREATED if creado else status.HTTP_200_OK,
        )


class AprendicesSinProyectoFichaView(APIView):
    """
    GET /api/v1/fichas/<uuid:ficha_id>/alertas-sin-proyecto/
    Lista aprendices activos sin equipo o sin proyecto publicado, y equipos con < 2 activos.
    """

    permission_classes = [EsInstructorOAdmin]

    def get(self, request, ficha_id):
        ficha = get_object_or_404(Ficha, id=ficha_id)
        matriculas_no_suspendidas = (
            ficha.matriculas.filter(activa=True)
            .exclude(aprendiz__estado_cuenta=EstadoCuenta.SUSPENDIDO)
            .select_related("aprendiz")
            .prefetch_related("aprendiz__membresias_grupo_scrum__grupo")
        )

        sin_grupo = []
        sin_proyecto = []
        for mat in matriculas_no_suspendidas:
            aprendiz = mat.aprendiz
            miembro = aprendiz.miembro_grupo_scrum
            if not miembro or miembro.ficha_id != ficha.id:
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
        for grupo in (
            ficha.grupos_scrum.exclude(estado=GrupoScrum.EstadoGrupo.ARCHIVADO)
            .prefetch_related("miembros__aprendiz")
            .all()
        ):
            activos = [
                m.aprendiz
                for m in grupo.miembros.all()
                if m.activo and m.aprendiz.estado_cuenta != EstadoCuenta.SUSPENDIDO
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
