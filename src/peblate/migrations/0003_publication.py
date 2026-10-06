import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("peblate", "0002_fontownership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [  # noqa: RUF012
        migrations.AlterField(
            model_name="languagejob",
            name="translation",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="trans.translation",
            ),
        ),
        migrations.AddField(
            model_name="languagejob",
            name="component",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="trans.component",
            ),
        ),
        migrations.AddField(
            model_name="languagejob",
            name="font_input_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="languagejob",
            name="coverage_language",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.CreateModel(
            name="PublicationSettings",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                (
                    "minimum_approved_percent",
                    models.PositiveSmallIntegerField(default=80),
                ),
                (
                    "component",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="trans.component",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="FontApproval",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("locale", models.CharField(max_length=80)),
                ("approved_at", models.DateTimeField(auto_now=True)),
                ("input_hash", models.CharField(max_length=64)),
                ("coverage_language", models.CharField(blank=True, max_length=80)),
                ("accepted_missing_characters", models.JSONField(default=dict)),
                ("unknown_baseline_accepted", models.BooleanField(default=False)),
                ("note", models.TextField()),
                (
                    "approved_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="trans.component",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("component", "locale"), name="peblate_font_approval"
                    )
                ]
            },
        ),
    ]
