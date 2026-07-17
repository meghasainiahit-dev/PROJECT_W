from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store_app", "0006_useraccessprofile_action_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="wholesale_price",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),
        migrations.AddField(
            model_name="product",
            name="retailer_price",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=10),
        ),
    ]
