from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("store_app", "0012_quotation_multiple_company_bank"),
    ]

    operations = [
        migrations.CreateModel(
            name="Lead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(db_index=True, max_length=180)),
                ("phone", models.CharField(db_index=True, max_length=30)),
                ("whatsapp_number", models.CharField(blank=True, max_length=30)),
                ("email", models.EmailField(blank=True, db_index=True, max_length=254)),
                ("company_name", models.CharField(blank=True, db_index=True, max_length=180)),
                ("designation", models.CharField(blank=True, max_length=120)),
                ("source", models.CharField(choices=[("website", "Website"), ("facebook", "Facebook"), ("instagram", "Instagram"), ("google_ads", "Google Ads"), ("whatsapp", "WhatsApp"), ("referral", "Referral"), ("cold_calling", "Cold Calling"), ("walk_in", "Walk-in"), ("linkedin", "LinkedIn"), ("indiamart", "IndiaMART"), ("justdial", "Justdial"), ("manual_entry", "Manual Entry"), ("other", "Other")], db_index=True, default="manual_entry", max_length=30)),
                ("priority", models.CharField(choices=[("hot", "Hot"), ("warm", "Warm"), ("cold", "Cold")], db_index=True, default="warm", max_length=10)),
                ("status", models.CharField(choices=[("new", "New"), ("contacted", "Contacted"), ("follow_up", "Follow-up"), ("interested", "Interested"), ("qualified", "Qualified"), ("proposal_sent", "Proposal Sent"), ("negotiation", "Negotiation"), ("converted", "Converted"), ("lost", "Lost"), ("not_interested", "Not Interested"), ("not_responding", "Not Responding")], db_index=True, default="new", max_length=30)),
                ("tags", models.CharField(blank=True, help_text="Comma-separated tags", max_length=500)),
                ("address", models.TextField(blank=True)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=100)),
                ("country", models.CharField(blank=True, max_length=100)),
                ("pincode", models.CharField(blank=True, max_length=15)),
                ("notes", models.TextField(blank=True)),
                ("lost_reason", models.CharField(blank=True, choices=[("price_too_high", "Price Too High"), ("not_interested", "Not Interested"), ("competitor_selected", "Competitor Selected"), ("no_response", "No Response"), ("budget_issue", "Budget Issue"), ("requirement_changed", "Requirement Changed"), ("invalid_lead", "Invalid Lead"), ("duplicate_lead", "Duplicate Lead"), ("other", "Other")], max_length=30)),
                ("lost_notes", models.TextField(blank=True)),
                ("lost_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_leads", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_leads", to=settings.AUTH_USER_MODEL)),
                ("lost_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lost_leads", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_leads", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="LeadActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event", models.CharField(choices=[("created", "Lead Created"), ("updated", "Lead Updated"), ("assigned", "Assigned to Employee"), ("status_changed", "Status Changed"), ("follow_up_added", "Follow-up Added"), ("follow_up_completed", "Follow-up Completed"), ("note_added", "Note Added"), ("proposal_sent", "Proposal Sent"), ("converted", "Lead Converted"), ("lost", "Lead Lost")], db_index=True, max_length=30)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_activities", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="store_app.lead")),
            ], options={"ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="LeadFollowUp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("follow_up_date", models.DateField(db_index=True)),
                ("follow_up_time", models.TimeField()),
                ("follow_up_type", models.CharField(choices=[("call", "Call"), ("whatsapp", "WhatsApp"), ("email", "Email"), ("meeting", "Meeting"), ("demo", "Demo")], max_length=20)),
                ("status", models.CharField(choices=[("upcoming", "Upcoming"), ("completed", "Completed"), ("missed", "Missed"), ("cancelled", "Cancelled")], db_index=True, default="upcoming", max_length=20)),
                ("notes", models.TextField(blank=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_follow_ups", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_lead_follow_ups", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="follow_ups", to="store_app.lead")),
            ], options={"ordering": ("follow_up_date", "follow_up_time", "id")},
        ),
        migrations.CreateModel(
            name="LeadNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_notes", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lead_notes", to="store_app.lead")),
            ], options={"ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="LeadConversion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("conversion_date", models.DateField()),
                ("product_service", models.CharField(max_length=255)),
                ("deal_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)])),
                ("payment_status", models.CharField(choices=[("pending", "Pending"), ("partial", "Partial"), ("paid", "Paid")], default="pending", max_length=20)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("converted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="converted_leads", to=settings.AUTH_USER_MODEL)),
                ("lead", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="conversion", to="store_app.lead")),
            ],
        ),
        migrations.CreateModel(
            name="LeadStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_status", models.CharField(choices=[("new", "New"), ("contacted", "Contacted"), ("follow_up", "Follow-up"), ("interested", "Interested"), ("qualified", "Qualified"), ("proposal_sent", "Proposal Sent"), ("negotiation", "Negotiation"), ("converted", "Converted"), ("lost", "Lost"), ("not_interested", "Not Interested"), ("not_responding", "Not Responding")], max_length=30)),
                ("new_status", models.CharField(choices=[("new", "New"), ("contacted", "Contacted"), ("follow_up", "Follow-up"), ("interested", "Interested"), ("qualified", "Qualified"), ("proposal_sent", "Proposal Sent"), ("negotiation", "Negotiation"), ("converted", "Converted"), ("lost", "Lost"), ("not_interested", "Not Interested"), ("not_responding", "Not Responding")], max_length=30)),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lead_status_changes", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="store_app.lead")),
            ], options={"ordering": ("-created_at", "-id")},
        ),
    ]
