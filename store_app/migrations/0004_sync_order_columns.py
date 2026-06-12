from django.db import migrations


def add_missing_order_columns(apps, schema_editor):
    table = "store_app_order"
    columns = {
        "buyer_tax_amount": "decimal(10,2) NOT NULL DEFAULT 0.00",
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
        ("store_app", "0003_sync_purchasebillitem_columns"),
    ]

    operations = [
        migrations.RunPython(add_missing_order_columns, migrations.RunPython.noop),
    ]
