from django.contrib import admin
from .models import Warehouse, Material, Delivery, ShelfSlot, ManufacturingOrder, MachineHealth, ScrapEvent, GlobalLog


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'num_docks', 'created_at')
    search_fields = ('name', 'code')


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'created_at')
    search_fields = ('name', 'category')


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ('id', 'manufacturer', 'date', 'size', 'batch_id', 'quantity', 'shelf_id', 'status', 'material', 'warehouse')
    list_filter = ('status', 'manufacturer', 'warehouse')
    search_fields = ('batch_id', 'manufacturer')


@admin.register(ShelfSlot)
class ShelfSlotAdmin(admin.ModelAdmin):
    list_display = ('shelf_id', 'slot_index', 'is_occupied', 'delivery', 'warehouse')
    list_filter = ('is_occupied', 'warehouse')
    search_fields = ('shelf_id',)


@admin.register(ManufacturingOrder)
class ManufacturingOrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'product', 'status', 'quality', 'processing_time', 'created_at')
    list_filter = ('status', 'quality')
    search_fields = ('order_id', 'product')


@admin.register(MachineHealth)
class MachineHealthAdmin(admin.ModelAdmin):
    list_display = ('machine_id', 'machine_name', 'usage_count', 'failure_threshold', 'updated_at')
    search_fields = ('machine_id', 'machine_name')


@admin.register(ScrapEvent)
class ScrapEventAdmin(admin.ModelAdmin):
    list_display = ('order', 'machine_name', 'scrap_type', 'scrap_rate', 'created_at')
    list_filter = ('machine_name', 'scrap_type')
    search_fields = ('machine_name',)


@admin.register(GlobalLog)
class GlobalLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'event_type', 'severity', 'title')
    list_filter = ('event_type', 'severity')
    search_fields = ('title', 'description')
    date_hierarchy = 'timestamp'
