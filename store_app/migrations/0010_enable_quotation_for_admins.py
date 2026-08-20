from django.db import migrations


def enable_quotation(apps, schema_editor):
    Profile = apps.get_model("store_app", "UserAccessProfile")
    for profile in Profile.objects.filter(role__in=("admin", "super_admin")):
        modules = list(profile.modules or [])
        permissions = dict(profile.action_permissions or {})
        if "quotation" not in modules:
            modules.append("quotation")
        permissions["quotation"] = ["view", "add", "edit", "delete"]
        profile.modules = modules
        profile.action_permissions = permissions
        profile.save(update_fields=("modules", "action_permissions"))


class Migration(migrations.Migration):
    dependencies = [("store_app", "0009_quotation_quotationsettings_quotationitem")]
    operations = [migrations.RunPython(enable_quotation, migrations.RunPython.noop)]
