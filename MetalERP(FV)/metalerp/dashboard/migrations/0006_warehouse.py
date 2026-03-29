from django.db import migrations, models
import django.db.models.deletion


def create_default_warehouse(apps, schema_editor):
    Warehouse = apps.get_model('dashboard', 'Warehouse')
    Delivery = apps.get_model('dashboard', 'Delivery')
    ShelfSlot = apps.get_model('dashboard', 'ShelfSlot')

    wh, _ = Warehouse.objects.get_or_create(
        code='WH-01',
        defaults={'name': 'Main Warehouse', 'num_docks': 3},
    )
    Delivery.objects.filter(warehouse__isnull=True).update(warehouse=wh)
    ShelfSlot.objects.filter(warehouse__isnull=True).update(warehouse=wh)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0005_machinehealth_manufacturingorder_delivery_scrapevent'),
    ]

    operations = [
        # 1. Create Warehouse model
        migrations.CreateModel(
            name='Warehouse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('code', models.CharField(max_length=20, unique=True)),
                ('num_docks', models.IntegerField(default=3)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        # 2. Add nullable warehouse FK to Delivery
        migrations.AddField(
            model_name='delivery',
            name='warehouse',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='deliveries',
                to='dashboard.warehouse',
            ),
        ),
        # 3. Add nullable warehouse FK to ShelfSlot
        migrations.AddField(
            model_name='shelfslot',
            name='warehouse',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='shelf_slots',
                to='dashboard.warehouse',
            ),
        ),
        # 4. Backfill existing data
        migrations.RunPython(create_default_warehouse, migrations.RunPython.noop),
        # 5. Update unique_together for ShelfSlot
        migrations.AlterUniqueTogether(
            name='shelfslot',
            unique_together={('warehouse', 'shelf_id', 'slot_index')},
        ),
    ]
