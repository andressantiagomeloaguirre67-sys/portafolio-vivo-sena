# Generated manually for Vortex ADSO Pro: Estado de originalidad en Proyecto

from django.db import migrations, models


def marcar_proyectos_existentes_originales(apps, schema_editor):
    Proyecto = apps.get_model("proyectos", "Proyecto")
    Proyecto.objects.filter(estado__in=["IDEA_APROBADA", "PUBLICADO"]).update(
        estado_originalidad="ORIGINAL"
    )


def revertir_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("proyectos", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="proyecto",
            name="estado_originalidad",
            field=models.CharField(
                choices=[
                    ("SIN_VALIDAR", "Sin validar"),
                    ("ORIGINAL", "Original"),
                    ("EN_DIFERENCIACION", "En diferenciación"),
                ],
                db_index=True,
                default="SIN_VALIDAR",
                max_length=20,
            ),
        ),
        migrations.RunPython(marcar_proyectos_existentes_originales, revertir_noop),
    ]
