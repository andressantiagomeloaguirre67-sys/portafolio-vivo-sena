# Generated manually for Regla No-Delete: archive legacy escalated consultations without physical deletion

from django.db import migrations, models


def archivar_consultas_pendientes(apps, schema_editor):
    ConsultaEscaladaInstructor = apps.get_model("revisiones", "ConsultaEscaladaInstructor")
    ConsultaEscaladaInstructor.objects.filter(estado="PENDIENTE").update(
        estado="archivada_por_cambio_de_politica"
    )


def revertir_archivo_consultas(apps, schema_editor):
    ConsultaEscaladaInstructor = apps.get_model("revisiones", "ConsultaEscaladaInstructor")
    ConsultaEscaladaInstructor.objects.filter(
        estado="archivada_por_cambio_de_politica"
    ).update(estado="PENDIENTE")


class Migration(migrations.Migration):

    dependencies = [
        ("revisiones", "0002_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="consultaescaladainstructor",
            name="estado",
            field=models.CharField(
                choices=[
                    ("PENDIENTE", "Pendiente (histórico)"),
                    ("ATENDIDA", "Atendida (histórico)"),
                    (
                        "archivada_por_cambio_de_politica",
                        "Archivada por cambio de política",
                    ),
                ],
                default="archivada_por_cambio_de_politica",
                max_length=40,
            ),
        ),
        migrations.RunPython(
            archivar_consultas_pendientes,
            reverse_code=revertir_archivo_consultas,
        ),
    ]
