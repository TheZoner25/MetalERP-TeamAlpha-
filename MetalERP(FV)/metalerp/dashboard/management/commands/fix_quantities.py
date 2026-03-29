import random
from django.core.management.base import BaseCommand
from dashboard.models import Delivery


class Command(BaseCommand):
    help = 'Fix delivery quantities: convert MT values to pallet counts (1-4)'

    def handle(self, *args, **options):
        fixed = 0
        for d in Delivery.objects.all():
            digits = ''.join(c for c in d.quantity if c.isdigit())
            if digits != d.quantity or (digits and int(digits) > 4):
                old = d.quantity
                d.quantity = str(random.randint(1, 4))
                d.save()
                fixed += 1
                self.stdout.write(f'  Fixed: delivery #{d.id} "{old}" → "{d.quantity}"')

        self.stdout.write(self.style.SUCCESS(f'Fixed {fixed} deliveries.'))
