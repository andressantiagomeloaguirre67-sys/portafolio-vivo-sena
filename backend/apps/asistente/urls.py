from django.urls import path
from .views import ConsultarAgenteGuardianView

urlpatterns = [
    path(
        "consultar/",
        ConsultarAgenteGuardianView.as_view(),
        name="asistente-consultar-guardian",
    ),
]
