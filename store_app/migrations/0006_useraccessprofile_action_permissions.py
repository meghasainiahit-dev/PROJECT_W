from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store_app", "0005_useraccessprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="useraccessprofile",
            name="action_permissions",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
