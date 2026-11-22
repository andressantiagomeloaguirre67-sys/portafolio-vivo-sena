from django.urls import path
from .views import (
    BuscadorGlobalInstructorView,
    ComentariosProyectoListCreateView,
    ReportesProyectoListCreateView,
    ResolverReporteProyectoView,
    ResponderComentarioGrupoView,
    ResumenDashboardInstructorView,
)

urlpatterns = [
    path(
        "resumen-instructor/",
        ResumenDashboardInstructorView.as_view(),
        name="revisiones-resumen-instructor",
    ),
    path(
        "buscador-instructor/",
        BuscadorGlobalInstructorView.as_view(),
        name="revisiones-buscador-instructor",
    ),
    path(
        "proyectos/<uuid:proyecto_id>/comentarios/",
        ComentariosProyectoListCreateView.as_view(),
        name="revisiones-comentarios-proyecto",
    ),
    path(
        "comentarios/<uuid:comentario_id>/responder/",
        ResponderComentarioGrupoView.as_view(),
        name="revisiones-responder-comentario",
    ),
    path(
        "reportes/",
        ReportesProyectoListCreateView.as_view(),
        name="revisiones-reportes",
    ),
    path(
        "reportes/<uuid:reporte_id>/resolver/",
        ResolverReporteProyectoView.as_view(),
        name="revisiones-resolver-reporte",
    ),
]
