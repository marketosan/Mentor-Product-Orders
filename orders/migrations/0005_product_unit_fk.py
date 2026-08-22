from django.db import migrations, models
import django.db.models.deletion


def populate_unit_fk(apps, schema_editor):
    """Point every product at a seeded Unit row -- "τμχ" for all of them.

    The seeded units are the shop's actual Greek measures, not the old
    English placeholders ("kg", "box", ...) this field used to hold, so
    nothing already in the database is expected to match one by name. The
    seed list is deliberately exact -- nothing gets invented here to patch
    over that mismatch. "τμχ" is the closest thing to a generic placeholder
    among the seeded units; an admin fixes the real ones individually from
    /products/units/ and the product edit dialog afterwards.
    """
    Product = apps.get_model("orders", "Product")
    Unit = apps.get_model("orders", "Unit")

    fallback = Unit.objects.get(name="τμχ")
    Product.objects.update(unit_new=fallback)


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_unit'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='unit_new',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='products',
                to='orders.unit',
            ),
        ),
        migrations.RunPython(populate_unit_fk, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='product',
            name='unit',
        ),
        migrations.RenameField(
            model_name='product',
            old_name='unit_new',
            new_name='unit',
        ),
        migrations.AlterField(
            model_name='product',
            name='unit',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='products',
                to='orders.unit',
            ),
        ),
    ]
