from django.urls import path
from .views import (
    ConfirmarSubidaProyectoView,
    DetalleProyectoView,
    EjecutarProyectoSandboxInfoView,
    FeedProyectosListView,
    HistorialBitacoraProyectoView,
    MiGrupoProyectoView,
    ObtenerUrlSubidaFirmadaProyectoView,
    RetirarProyectoInstructorView,
    SubirReemplazarCodigoProyectoView,
    ValidarIdeaProyectoView,
)

urlpatterns = [
    path("feed/", FeedProyectosListView.as_view(), name="proyectos-feed"),
    path(
        "validar-idea/",
        ValidarIdeaProyectoView.as_view(),
        name="proyectos-validar-idea",
    ),
    path("mi-grupo/", MiGrupoProyectoView.as_view(), name="proyectos-mi-grupo"),
    path(
        "mi-grupo/subir-codigo/",
        SubirReemplazarCodigoProyectoView.as_view(),
        name="proyectos-subir-reemplazar-codigo",
    ),
    path(
        "<uuid:proyecto_id>/",
        DetalleProyectoView.as_view(),
        name="proyectos-detalle",
    ),
    path(
        "<uuid:proyecto_id>/url-subida/",
        ObtenerUrlSubidaFirmadaProyectoView.as_view(),
        name="proyectos-url-subida-firmada",
    ),
    path(
        "<uuid:proyecto_id>/confirmar-subida/",
        ConfirmarSubidaProyectoView.as_view(),
        name="proyectos-confirmar-subida",
    ),
    path(
        "<uuid:proyecto_id>/ejecutar/",
        EjecutarProyectoSandboxInfoView.as_view(),
        name="proyectos-ejecutar-info",
    ),
    path(
        "<uuid:proyecto_id>/retirar-instructor/",
        RetirarProyectoInstructorView.as_view(),
        name="proyectos-retirar-instructor",
    ),
    path(
        "<uuid:proyecto_id>/historial/",
        HistorialBitacoraProyectoView.as_view(),
        name="proyectos-historial-bitacora",
    ),
]
