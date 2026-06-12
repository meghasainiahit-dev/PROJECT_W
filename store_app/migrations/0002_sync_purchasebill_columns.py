from django.db import migrations


def add_missing_purchasebill_columns(apps, schema_editor):
    table = "store_app_purchasebill"
    columns = {
        "place_of_supply": "varchar(100) NULL",
        "gst_type": "varchar(20) NOT NULL DEFAULT 'with_gst'",
        "sgst_percent": "decimal(5,2) NOT NULL DEFAULT 0.00",
        "cgst_percent": "decimal(5,2) NOT NULL DEFAULT 0.00",
        "igst_percent": "decimal(5,2) NOT NULL DEFAULT 0.00",
        "subtotal": "decimal(12,2) NOT NULL DEFAULT 0.00",
        "tax_amount": "decimal(10,2) NOT NULL DEFAULT 0.00",
        "discount": "decimal(10,2) NOT NULL DEFAULT 0.00",
        "shipping": "decimal(10,2) NOT NULL DEFAULT 0.00",
        "other_expense": "decimal(10,2) NOT NULL DEFAULT 0.00",
        "round_off": "decimal(5,2) NOT NULL DEFAULT 0.00",
        "payment_due_date": "date NULL",
        "payment_mode": "varchar(20) NULL",
        "transaction_id": "varchar(100) NULL",
        "is_deleted": "bool NOT NULL DEFAULT 0",
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
        ("store_app", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_missing_purchasebill_columns, migrations.RunPython.noop),
    ]
