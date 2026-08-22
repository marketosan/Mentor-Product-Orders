from django.db import migrations, models

# The starting set of units, singular -> plural. "τμχ" reads the same either
# way, so its pair is given explicitly rather than guessed with a suffix, same
# as every other entry here.
UNIT_PAIRS = {
    ("σακούλα", "σακούλες"),
    ("κούτα", "κούτες"),
    ("καφάσι", "καφάσια"),
    ("τμχ", "τμχ"),
    ("κιλό", "κιλά"),
    ("συσκευασία", "συσκευασίες"),
    ("κιβώτιο", "κιβώτια"),
    ("κονσέρβα", "κονσέρβες"),
    ("βάζο", "βάζα"),
    ("ματσάκι", "ματσάκια"),
    ("πακέτο", "πακέτα"),
    ("κεσεδάκι", "κεσεδάκια"),
    ("τσαμπί", "τσαμπιά"),
    ("δεσμίδα", "δεσμίδες"),
    ("ρολό", "ρολά"),
    ("μπετόνι", "μπετόνια"),
    ("σακουλάκι", "σακουλάκια"),
    ("εξάδα", "εξάδες"),
}


def seed_units(apps, schema_editor):
    Unit = apps.get_model("orders", "Unit")
    Unit.objects.bulk_create(
        [Unit(name=name, plural=plural) for name, plural in UNIT_PAIRS]
    )


def remove_seeded_units(apps, schema_editor):
    Unit = apps.get_model("orders", "Unit")
    Unit.objects.filter(name__in=[name for name, _ in UNIT_PAIRS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_alter_orderitem_unit_price_snapshot_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Unit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=20, unique=True)),
                ('plural', models.CharField(max_length=20)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.RunPython(seed_units, remove_seeded_units),
    ]
