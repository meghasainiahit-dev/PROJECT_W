from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_settings(apps, schema_editor):
    Settings = apps.get_model("store_app", "QuotationSettings")
    Company = apps.get_model("store_app", "QuotationCompanyProfile")
    Bank = apps.get_model("store_app", "QuotationBankAccount")
    Quotation = apps.get_model("store_app", "Quotation")
    legacy = Settings.objects.first()
    if not legacy:
        return
    company = Company.objects.create(
        label=legacy.company_name or "Default Company",
        company_name=legacy.company_name or "Company Name",
        address=legacy.address, gstin=legacy.gstin, phone=legacy.phone,
        email=legacy.email, terms=legacy.terms,
    )
    bank = None
    if legacy.bank_name or legacy.account_number:
        bank = Bank.objects.create(
            label=legacy.bank_name or "Default Bank", bank_name=legacy.bank_name or "Bank",
            account_name=legacy.account_name, account_number=legacy.account_number,
            ifsc=legacy.ifsc, branch=legacy.branch,
        )
    Quotation.objects.update(company_profile=company, bank_account=bank)


class Migration(migrations.Migration):
    dependencies = [("store_app", "0011_quotation_tally_fields")]
    operations = [
        migrations.CreateModel(
            name="QuotationCompanyProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=120)),
                ("company_name", models.CharField(max_length=180)),
                ("address", models.TextField(blank=True)),
                ("gstin", models.CharField(blank=True, max_length=30)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("terms", models.TextField(blank=True, default="Quotation valid for 15 days.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ], options={"ordering": ("label", "id")},
        ),
        migrations.CreateModel(
            name="QuotationBankAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=120)),
                ("bank_name", models.CharField(max_length=120)),
                ("account_name", models.CharField(blank=True, max_length=120)),
                ("account_number", models.CharField(max_length=60)),
                ("ifsc", models.CharField(blank=True, max_length=30)),
                ("branch", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ], options={"ordering": ("label", "id")},
        ),
        migrations.AddField(
            model_name="quotation", name="company_profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="quotations", to="store_app.quotationcompanyprofile"),
        ),
        migrations.AddField(
            model_name="quotation", name="bank_account",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="quotations", to="store_app.quotationbankaccount"),
        ),
        migrations.RunPython(migrate_legacy_settings, migrations.RunPython.noop),
    ]
