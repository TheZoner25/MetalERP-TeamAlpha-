import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from dashboard.models import GlobalLog, Delivery, ManufacturingOrder, MachineHealth


class Command(BaseCommand):
    help = 'Seed sample GlobalLog entries for demo purposes'

    def handle(self, *args, **options):
        now = timezone.now()
        logs_created = 0

        deliveries = list(Delivery.objects.all()[:20])
        orders = list(ManufacturingOrder.objects.all()[:20])
        machines = list(MachineHealth.objects.all())

        entries = []

        # Delivery events
        for i, d in enumerate(deliveries[:8]):
            ts = now - timedelta(hours=random.randint(1, 72), minutes=random.randint(0, 59))
            entries.append(GlobalLog(
                timestamp=ts,
                event_type='delivery',
                severity='info',
                title=f'Delivery added: {d.batch_id}',
                description=f'From {d.manufacturer}, qty {d.quantity}, shelf {d.shelf_id}',
                delivery=d,
            ))

        # Some stored
        for d in deliveries[2:5]:
            ts = now - timedelta(hours=random.randint(1, 48), minutes=random.randint(0, 59))
            entries.append(GlobalLog(
                timestamp=ts,
                event_type='shipment',
                severity='info',
                title=f'Delivery stored: {d.batch_id}',
                description=f'All pallets placed on shelf {d.shelf_id}',
                delivery=d,
            ))

        # Deleted delivery
        if deliveries:
            d = deliveries[0]
            ts = now - timedelta(hours=random.randint(1, 24))
            entries.append(GlobalLog(
                timestamp=ts,
                event_type='delivery',
                severity='warning',
                title=f'Delivery deleted: {d.batch_id}',
                description='Reason: Damaged on arrival',
                delivery=d,
            ))

        # Manufacturing events
        for o in orders[:10]:
            ts = now - timedelta(hours=random.randint(1, 60), minutes=random.randint(0, 59))
            if o.status == 'defected':
                entries.append(GlobalLog(
                    timestamp=ts,
                    event_type='manufacturing',
                    severity='error',
                    title=f'Order defected: {o.order_id}',
                    description=f'Defect at {o.defect_machine}: {o.defect_type} — {o.defect_cause}',
                    manufacturing_order=o,
                ))
            else:
                entries.append(GlobalLog(
                    timestamp=ts,
                    event_type='manufacturing',
                    severity='info',
                    title=f'Order completed: {o.order_id}',
                    description=f'{o.product}, {o.processing_time:.1f}s processing, quality {o.quality}',
                    manufacturing_order=o,
                ))

        # Machine events
        for m in machines:
            # Maintenance reset
            ts = now - timedelta(hours=random.randint(12, 96))
            entries.append(GlobalLog(
                timestamp=ts,
                event_type='machine',
                severity='info',
                title=f'Machine reset: {m.machine_name} ({m.machine_id})',
                description='Usage counter reset to 0, maintenance timestamp updated',
                machine=m,
            ))

            # Some wear warnings
            if random.random() > 0.5:
                ts = now - timedelta(hours=random.randint(1, 36))
                entries.append(GlobalLog(
                    timestamp=ts,
                    event_type='machine',
                    severity='warning',
                    title=f'Machine wear high: {m.machine_name}',
                    description=f'Usage {int(m.failure_threshold * 0.85)}/{m.failure_threshold}',
                    machine=m,
                ))

        # Critical machine event
        if machines:
            m = random.choice(machines)
            ts = now - timedelta(hours=random.randint(1, 12))
            entries.append(GlobalLog(
                timestamp=ts,
                event_type='machine',
                severity='critical',
                title=f'Machine at failure threshold: {m.machine_name}',
                description=f'Usage {m.failure_threshold}/{m.failure_threshold}',
                machine=m,
            ))

        # Threshold updates
        for m in machines[:3]:
            ts = now - timedelta(hours=random.randint(24, 120))
            entries.append(GlobalLog(
                timestamp=ts,
                event_type='threshold',
                severity='info',
                title=f'Threshold updated: {m.machine_name}',
                description=f'New threshold: {m.failure_threshold}',
                machine=m,
            ))

        # Scrap events
        for o in orders[:5]:
            if random.random() > 0.4:
                ts = now - timedelta(hours=random.randint(1, 48))
                machine_name = random.choice(machines).machine_name if machines else 'Unknown'
                entries.append(GlobalLog(
                    timestamp=ts,
                    event_type='scrap',
                    severity='warning',
                    title=f'Scrap at {machine_name}',
                    description=f'Order {o.order_id}: Edge crack ({random.uniform(1, 8):.2f}%)',
                    manufacturing_order=o,
                ))

        # Bulk create
        GlobalLog.objects.bulk_create(entries)
        logs_created = len(entries)

        self.stdout.write(self.style.SUCCESS(f'Created {logs_created} sample log entries'))
