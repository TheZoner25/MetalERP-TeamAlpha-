from rest_framework import serializers
from dashboard.models import *

# ✅ Material
class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = '__all__'


# ✅ Warehouse
class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = '__all__'


# ✅ Delivery
class DeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = Delivery
        fields = '__all__'


# ✅ Manufacturing Order
class ManufacturingOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManufacturingOrder
        fields = '__all__'


# ✅ Machine Health
class MachineHealthSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineHealth
        fields = '__all__'


# ✅ Scrap Event
class ScrapEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScrapEvent
        fields = '__all__'


# ✅ Shelf Slot
class ShelfSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShelfSlot
        fields = '__all__'


# ✅ Global Log
class GlobalLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalLog
        fields = '__all__'