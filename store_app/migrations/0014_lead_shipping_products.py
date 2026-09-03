from django.db import migrations, models


def copy_legacy_customer_data(apps, schema_editor):
    Lead = apps.get_model("store_app", "Lead")
    for lead in Lead.objects.all().iterator():
        lead.shipping_name = lead.full_name
        lead.shipping_phone = lead.whatsapp_number
        lead.shipping_address1 = lead.address
        lead.shipping_city = lead.city
        lead.shipping_zip = lead.pincode
        lead.shipping_province = lead.state
        lead.shipping_province_name = lead.state
        lead.shipping_country = lead.country or "India"
        lead.save(update_fields=[
            "shipping_name", "shipping_phone", "shipping_address1",
            "shipping_city", "shipping_zip", "shipping_province",
            "shipping_province_name", "shipping_country",
        ])


class Migration(migrations.Migration):
    dependencies = [
        ("store_app", "0013_lead_management"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="country_code",
            field=models.CharField(default="+91", max_length=8),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_address1",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_address2",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_city",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_country",
            field=models.CharField(blank=True, default="India", max_length=100),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_name",
            field=models.CharField(blank=True, db_index=True, max_length=180),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_province",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_province_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="lead",
            name="shipping_zip",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="lead",
            name="products",
            field=models.ManyToManyField(blank=True, related_name="leads", to="store_app.product"),
        ),
        migrations.RunPython(copy_legacy_customer_data, migrations.RunPython.noop),
    ]
