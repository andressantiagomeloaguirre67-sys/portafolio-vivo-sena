# Generated manually for Vortex ADSO Pro: Equipos Scrum directos + membresías históricas con unicidad parcial

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def poblar_ficha_membresias_y_estado_grupos(apps, schema_editor):
    MiembroGrupoScrum = apps.get_model("fichas", "MiembroGrupoScrum")
    GrupoScrum = apps.get_model("fichas", "GrupoScrum")
    Proyecto = apps.get_model("proyectos", "Proyecto")

    # 1. Backfill de ficha en membresías existentes
    for miembro in MiembroGrupoScrum.objects.select_related("grupo").all():
        miembro.ficha_id = miembro.grupo.ficha_id
        miembro.activo = True
        miembro.save(update_fields=["ficha", "activo"])

    # 2. Marcar como PUBLICADO los grupos existentes cuyo proyecto ya está publicado
    grupos_publicados_ids = set(
        Proyecto.objects.filter(estado="PUBLICADO").values_list("grupo_scrum_id", flat=True)
    )
    if grupos_publicados_ids:
        GrupoScrum.objects.filter(id__in=grupos_publicados_ids).update(estado="PUBLICADO")


def revertir_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("fichas", "0002_initial"),
        ("proyectos", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="gruposcrum",
            name="uq_nombre_grupo_por_ficha",
        ),
        migrations.AddField(
            model_name="gruposcrum",
            name="estado",
            field=models.CharField(
                choices=[
                    ("BORRADOR", "Borrador"),
                    ("PUBLICADO", "Publicado"),
                    ("ARCHIVADO", "Archivado"),
                ],
                db_index=True,
                default="BORRADOR",
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name="gruposcrum",
            name="archivado_en",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="miembrogruposcrum",
            name="ficha",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="membresias_grupo_scrum",
                to="fichas.ficha",
            ),
        ),
        migrations.AddField(
            model_name="miembrogruposcrum",
            name="rol_scrum",
            field=models.CharField(
                choices=[
                    ("SCRUM_MASTER", "Scrum Master"),
                    ("PRODUCT_OWNER", "Product Owner"),
                    ("DEVELOPER", "Developer"),
                ],
                default="DEVELOPER",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="miembrogruposcrum",
            name="activo",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name="miembrogruposcrum",
            name="fecha_fin",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="miembrogruposcrum",
            name="aprendiz",
            field=models.ForeignKey(
                limit_choices_to={"rol": "APRENDIZ"},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="membresias_grupo_scrum",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="miembrogruposcrum",
            name="grupo",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="miembros",
                to="fichas.gruposcrum",
            ),
        ),
        migrations.AlterModelOptions(
            name="miembrogruposcrum",
            options={
                "ordering": ["-activo", "fecha_ingreso"],
                "verbose_name": "Miembro de Grupo Scrum",
                "verbose_name_plural": "Miembros de Grupos Scrum",
            },
        ),
        migrations.RunPython(poblar_ficha_membresias_y_estado_grupos, revertir_noop),
        migrations.AlterField(
            model_name="miembrogruposcrum",
            name="ficha",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="membresias_grupo_scrum",
                to="fichas.ficha",
            ),
        ),
        migrations.AddConstraint(
            model_name="gruposcrum",
            constraint=models.UniqueConstraint(
                condition=Q(("estado", "ARCHIVADO"), _negated=True),
                fields=("ficha", "nombre_grupo"),
                name="uq_nombre_grupo_activo_por_ficha",
            ),
        ),
        migrations.AddConstraint(
            model_name="miembrogruposcrum",
            constraint=models.UniqueConstraint(
                condition=Q(("activo", True)),
                fields=("ficha", "aprendiz"),
                name="uq_un_grupo_activo_por_ficha_y_aprendiz",
            ),
        ),
        migrations.AddConstraint(
            model_name="miembrogruposcrum",
            constraint=models.UniqueConstraint(
                condition=Q(("activo", True), ("rol_scrum", "SCRUM_MASTER")),
                fields=("grupo",),
                name="uq_un_scrum_master_activo_por_grupo",
            ),
        ),
        migrations.AddConstraint(
            model_name="miembrogruposcrum",
            constraint=models.UniqueConstraint(
                condition=Q(("activo", True), ("rol_scrum", "PRODUCT_OWNER")),
                fields=("grupo",),
                name="uq_un_product_owner_activo_por_grupo",
            ),
        ),
    ]
