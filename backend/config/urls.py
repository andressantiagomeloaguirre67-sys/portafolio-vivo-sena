from pathlib import Path
from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.proyectos.views import SandboxEjecucionProyectoView

META1D_DIR = Path(settings.BASE_DIR).parent / "frontend" / "meta1d-hero"
FRONTEND_SPA_HTML = Path(settings.BASE_DIR).parent / "frontend" / "index.html"


def servir_hero_meta1d_index(request):
    """Sirve la pantalla Hero 3D (meta1D) apenas se ingresa a la raíz del sistema."""
    ruta = META1D_DIR / "index.html"
    return HttpResponse(
        ruta.read_text(encoding="utf-8"),
        content_type="text/html; charset=utf-8",
    )


def servir_hero_meta1d_css(request):
    ruta = META1D_DIR / "style.css"
    return HttpResponse(
        ruta.read_text(encoding="utf-8"),
        content_type="text/css; charset=utf-8",
    )


def servir_hero_meta1d_js(request):
    ruta = META1D_DIR / "app.js"
    return HttpResponse(
        ruta.read_text(encoding="utf-8"),
        content_type="application/javascript; charset=utf-8",
    )


def servir_hero_asset(request, filename: str):
    """Sirve imágenes y texturas 3D del directorio meta1d-hero."""
    ruta = (META1D_DIR / filename).resolve()
    if not str(ruta).startswith(str(META1D_DIR.resolve())) or not ruta.is_file():
        return HttpResponse(status=404)
    ext = ruta.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
    }
    return HttpResponse(
        ruta.read_bytes(),
        content_type=mime_map.get(ext, "application/octet-stream"),
    )


def servir_plataforma_spa(request):
    """Sirve la plataforma completa multi-rol (Aprendiz / Instructor / Admin + Sandbox)."""
    return HttpResponse(
        FRONTEND_SPA_HTML.read_text(encoding="utf-8"),
        content_type="text/html; charset=utf-8",
    )


def api_health_status(request):
    """Retorna el estado de salud del Backend Python/Django y PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT version();")
        pg_version = cursor.fetchone()[0]

    return JsonResponse(
        {
            "proyecto": "Portafolio Vivo SENA ADSO - Backend API",
            "version": "2.0.0",
            "estado": "ONLINE",
            "motor_backend": "Python + Django REST Framework + SimpleJWT",
            "base_de_datos": pg_version,
            "landing_hero_3d": "/",
            "plataforma_multi_rol": "/app/",
            "documentacion_swagger": "/api/docs/",
            "panel_admin": "/admin/",
            "modulos_activos": [
                "/api/v1/auth/",
                "/api/v1/fichas/",
                "/api/v1/proyectos/",
                "/api/v1/revisiones/",
                "/api/v1/asistente/",
            ],
        }
    )


urlpatterns = [
    # 1. Pantalla de bienvenida Hero 3D al entrar al sistema
    path("", servir_hero_meta1d_index, name="hero-entry"),
    path("style.css", servir_hero_meta1d_css, name="hero-css"),
    path("app.js", servir_hero_meta1d_js, name="hero-js"),
    path("assets/<str:filename>", servir_hero_asset, name="hero-asset"),
    path("aegis_robot.png", lambda r: servir_hero_asset(r, "aegis_robot.png"), name="aegis-robot-png"),
    path("aegis_head.png", lambda r: servir_hero_asset(r, "aegis_head.png"), name="aegis-head-png"),
    path("aegis_body.png", lambda r: servir_hero_asset(r, "aegis_body.png"), name="aegis-body-png"),
    # 2. Plataforma Principal Multi-Rol (Aprendiz / Instructor / Admin + Sandbox)
    path("app/", servir_plataforma_spa, name="plataforma-spa"),
    # 3. Estado y Administración
    path("api/v1/health/", api_health_status, name="api-health"),
    path("admin/", admin.site.urls),
    # 4. Sandbox aislado para ejecución en vivo de proyectos (iframe o pestaña directa)
    path(
        "sandbox/<uuid:proyecto_id>/",
        SandboxEjecucionProyectoView.as_view(),
        name="sandbox-ejecucion-raiz",
    ),
    path(
        "sandbox/<uuid:proyecto_id>/<path:recurso>",
        SandboxEjecucionProyectoView.as_view(),
        name="sandbox-ejecucion",
    ),
    # 5. Documentación OpenAPI / Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # 6. Los 5 Módulos del Portafolio Vivo SENA (v1)
    path("api/v1/auth/", include("apps.usuarios.urls")),
    path("api/v1/fichas/", include("apps.fichas.urls")),
    path("api/v1/proyectos/", include("apps.proyectos.urls")),
    path("api/v1/revisiones/", include("apps.revisiones.urls")),
    path("api/v1/asistente/", include("apps.asistente.urls")),
]
