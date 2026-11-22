from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.usuarios.permissions import EsAprendizActivo
from .services import procesar_consulta_agente_guardian


class ConsultaAgenteGuardianSerializer(serializers.Serializer):
    titulo_propuesto = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=""
    )
    mensaje = serializers.CharField(
        help_text="Describe la idea de proyecto de tu Grupo Scrum o tu inquietud."
    )
    historial = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="Historial reciente de la conversación para mantener el hilo.",
    )


class ConsultarAgenteGuardianView(APIView):
    """
    POST /api/v1/asistente/consultar/
    Aegis actúa como un colega técnico senior y tutor académico del SENA que razona,
    analiza la originalidad en PostgreSQL y guía paso a paso con una pregunta a la vez.
    """

    permission_classes = [EsAprendizActivo]

    def post(self, request):
        serializer = ConsultaAgenteGuardianSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resultado = procesar_consulta_agente_guardian(
            aprendiz=request.user,
            mensaje=serializer.validated_data["mensaje"],
            titulo_propuesto=serializer.validated_data.get("titulo_propuesto", ""),
            historial=serializer.validated_data.get("historial", []),
        )
        return Response(resultado, status=status.HTTP_200_OK)
