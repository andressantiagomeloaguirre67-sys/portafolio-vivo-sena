from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ActivarCuentaAprendizView,
    CambiarClaveView,
    ConfirmarRecuperacionClaveView,
    GestionInstructoresView,
    LoginPorDocumentoView,
    PerfilActualView,
    ReactivarAprendizView,
    ReenviarActivacionAprendizView,
    SolicitarRecuperacionClaveView,
    SuspenderAprendizView,
)

urlpatterns = [
    path("login/", LoginPorDocumentoView.as_view(), name="auth-login-documento"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("me/", PerfilActualView.as_view(), name="auth-perfil-actual"),
    path(
        "activar-cuenta/",
        ActivarCuentaAprendizView.as_view(),
        name="auth-activar-cuenta",
    ),
    path(
        "reenviar-activacion/",
        ReenviarActivacionAprendizView.as_view(),
        name="auth-reenviar-activacion",
    ),
    path(
        "recuperar-clave/solicitar/",
        SolicitarRecuperacionClaveView.as_view(),
        name="auth-recuperar-clave-solicitar",
    ),
    path(
        "recuperar-clave/confirmar/",
        ConfirmarRecuperacionClaveView.as_view(),
        name="auth-recuperar-clave-confirmar",
    ),
    path(
        "cambiar-clave/",
        CambiarClaveView.as_view(),
        name="auth-cambiar-clave",
    ),
    path(
        "instructores/",
        GestionInstructoresView.as_view(),
        name="auth-gestion-instructores",
    ),
    path(
        "aprendices/<uuid:aprendiz_id>/suspender/",
        SuspenderAprendizView.as_view(),
        name="auth-suspender-aprendiz",
    ),
    path(
        "aprendices/<uuid:aprendiz_id>/reactivar/",
        ReactivarAprendizView.as_view(),
        name="auth-reactivar-aprendiz",
    ),
]
