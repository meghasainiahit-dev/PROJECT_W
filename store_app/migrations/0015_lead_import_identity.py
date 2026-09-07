from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("store_app", "0014_lead_shipping_products"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="external_checkout_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="external_source",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
