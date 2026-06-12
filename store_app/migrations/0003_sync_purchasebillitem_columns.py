from django.db import migrations


def add_missing_purchasebillitem_columns(apps, schema_editor):
    table = "store_app_purchasebillitem"
    columns = {
        "total_price": "decimal(12,2) NOT NULL DEFAULT 0.00",
        "amount": "decimal(12,2) NOT NULL DEFAULT 0.00",
        "price": "decimal(10,2) NOT NULL DEFAULT 0.00",
    }

    with schema_editor.connection.cursor() as cursor:
        existing = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table
            )
        }

        for column_name, definition in columns.items():
            if column_name not in existing:
                cursor.execute(
                    f"ALTER TABLE {schema_editor.quote_name(table)} "
                    f"ADD COLUMN {schema_editor.quote_name(column_name)} {definition}"
                )


class Migration(migrations.Migration):

    dependencies = [
        ("store_app", "0002_sync_purchasebill_columns"),
    ]

    operations = [
        migrations.RunPython(add_missing_purchasebillitem_columns, migrations.RunPython.noop),
    ]
