from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from dashboard.models import Delivery, ShelfSlot


@api_view(['GET'])
@permission_classes([HasAPIKey])
def delivery_statuses(request):
    deliveries = Delivery.objects.all()

    data = {}
    pending_count = 0
    stored_count = 0

    for d in deliveries:
        # count status
        if d.status == 'pending':
            pending_count += 1
        elif d.status == 'stored':
            stored_count += 1

        # count shelf occupancy
        slots = ShelfSlot.objects.filter(delivery=d)
        occupied = slots.count()

        data[str(d.id)] = {
            "status": d.status,
            "shelf_id": d.shelf_id,
            "shelf_occupied": occupied,
            "shelf_full": occupied >= 4   # adjust if needed
        }

    total_slots = ShelfSlot.objects.count()
    occupied_slots = ShelfSlot.objects.filter(is_occupied=True).count()

    return Response({
        "deliveries": data,
        "pending_count": pending_count,
        "stored_count": stored_count,
        "occupied_slots": occupied_slots,
        "total_slots": total_slots
    })

# Create your views here.
