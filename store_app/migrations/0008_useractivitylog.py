from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("store_app", "0007_product_sale_prices"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event", models.CharField(db_index=True, max_length=100)),
                ("screen", models.CharField(blank=True, db_index=True, max_length=100)),
                ("target", models.CharField(blank=True, max_length=150)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("client_timestamp", models.DateTimeField(blank=True, null=True)),
                ("app_version", models.CharField(blank=True, max_length=40)),
                ("device_id", models.CharField(blank=True, db_index=True, max_length=128)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activity_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="useractivitylog",
            index=models.Index(fields=["user", "-created_at"], name="activity_user_created_idx"),
        ),
    ]
