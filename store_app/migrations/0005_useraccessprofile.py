from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("store_app", "0004_sync_order_columns"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserAccessProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("super_admin", "Super Admin"), ("admin", "Admin"), ("user", "User")], default="user", max_length=20)),
                ("modules", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="access_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
