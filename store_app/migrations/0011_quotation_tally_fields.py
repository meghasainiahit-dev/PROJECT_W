from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("store_app", "0010_enable_quotation_for_admins")]
    operations = [
        migrations.AddField(model_name="quotation",name="customer_state",field=models.CharField(blank=True,max_length=80)),
        migrations.AddField(model_name="quotation",name="customer_state_code",field=models.CharField(blank=True,max_length=10)),
        migrations.AddField(model_name="quotation",name="consignee_name",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="quotation",name="consignee_address",field=models.TextField(blank=True)),
        migrations.AddField(model_name="quotation",name="consignee_gstin",field=models.CharField(blank=True,max_length=30)),
        migrations.AddField(model_name="quotation",name="consignee_state",field=models.CharField(blank=True,max_length=80)),
        migrations.AddField(model_name="quotation",name="consignee_state_code",field=models.CharField(blank=True,max_length=10)),
        migrations.AddField(model_name="quotation",name="payment_terms",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="quotation",name="buyer_reference",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="quotation",name="other_references",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="quotation",name="dispatched_through",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="quotation",name="destination",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="quotation",name="delivery_terms",field=models.TextField(blank=True)),
        migrations.AddField(model_name="quotationitem",name="due_on",field=models.DateField(blank=True,null=True)),
        migrations.AddField(model_name="quotationitem",name="unit",field=models.CharField(default="PCS",max_length=20)),
        migrations.AddField(model_name="quotationitem",name="discount_percentage",field=models.DecimalField(decimal_places=2,default=0,max_digits=5)),
    ]
