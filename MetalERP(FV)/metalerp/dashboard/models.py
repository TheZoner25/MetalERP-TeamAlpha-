from django.db import models


class Warehouse(models.Model):
    SHAPE_CHOICES = [('rectangle', 'Rectangle'), ('circle', 'Circle'), ('custom', 'Custom')]

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    num_docks = models.IntegerField(default=3)
    # Layout configuration
    shape = models.CharField(max_length=20, choices=SHAPE_CHOICES, default='rectangle')
    width_m = models.FloatField(default=50.0)
    length_m = models.FloatField(default=50.0)
    height_m = models.FloatField(default=10.0)
    grid_cols = models.IntegerField(default=10)
    grid_rows = models.IntegerField(default=10)
    shelves_per_unit = models.IntegerField(default=6)
    slots_per_shelf = models.IntegerField(default=4)
    layout_configured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.code})'


class Material(models.Model):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.category})'


class Delivery(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('stored', 'Stored'), ('deleted', 'Deleted')]

    manufacturer = models.CharField(max_length=200)
    date = models.DateField()
    size = models.CharField(max_length=100)
    batch_id = models.CharField(max_length=50, unique=True)
    quantity = models.CharField(max_length=50)
    shelf_id = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    warehouse = models.ForeignKey('Warehouse', null=True, blank=True, on_delete=models.CASCADE, related_name='deliveries')
    material = models.ForeignKey(Material, null=True, blank=True, on_delete=models.SET_NULL)
    delete_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f'Delivery #{self.id} — {self.manufacturer} ({self.batch_id})'


class ManufacturingOrder(models.Model):
    STATUS_CHOICES = [('completed', 'Completed'), ('defected', 'Defected')]

    order_id = models.CharField(max_length=20, unique=True)       # WO-1001
    product = models.CharField(max_length=200)                     # HR Coil 2.5mm
    dimensions = models.CharField(max_length=100)                  # 3.0mm x 1209mm
    material = models.ForeignKey(Material, null=True, blank=True, on_delete=models.SET_NULL)
    material_name = models.CharField(max_length=200, blank=True)
    delivery = models.ForeignKey('Delivery', null=True, blank=True, on_delete=models.SET_NULL, related_name='manufacturing_orders')
    delivery_batch = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=200, blank=True)    # vendor
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    processing_time = models.FloatField(default=0)                 # seconds
    total_energy = models.FloatField(default=0)                    # kWh
    total_scrap = models.FloatField(default=0)                     # %
    quality = models.CharField(max_length=10, default='PASS')      # PASS or FAIL
    # Defect fields (populated only when status=defected)
    defect_machine = models.CharField(max_length=200, blank=True)
    defect_machine_id = models.CharField(max_length=20, blank=True)
    defect_type = models.CharField(max_length=200, blank=True)
    defect_cause = models.CharField(max_length=300, blank=True)
    stages_completed = models.IntegerField(default=5)
    # Stage data stored as JSON
    stage_data = models.JSONField(default=list, blank=True)        # [{metrics...}, ...]
    stage_timestamps = models.JSONField(default=list, blank=True)  # ["3:35:31 AM", ...]
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order_id} — {self.product} ({self.status})'


class MachineHealth(models.Model):
    machine_id = models.CharField(max_length=20, unique=True)       # MCH-UL-01
    machine_name = models.CharField(max_length=200)
    usage_count = models.IntegerField(default=0)
    failure_threshold = models.IntegerField(default=500)
    position = models.PositiveIntegerField(default=0, db_index=True)  # pipeline order
    last_maintenance = models.DateTimeField(null=True, blank=True)
    detail_data = models.JSONField(default=dict, blank=True)        # resources, parts, maintenance log, equipment info
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position']

    def __str__(self):
        return f'{self.machine_name} ({self.machine_id}) — {self.usage_count}/{self.failure_threshold}'


class ScrapEvent(models.Model):
    order = models.ForeignKey(ManufacturingOrder, on_delete=models.CASCADE, related_name='scrap_events')
    machine_name = models.CharField(max_length=200)
    machine_id = models.CharField(max_length=20)
    machine_index = models.IntegerField()
    scrap_type = models.CharField(max_length=100)
    scrap_rate = models.FloatField()
    material_name = models.CharField(max_length=200, blank=True)
    delivery_batch = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Scrap from {self.order.order_id} at {self.machine_name} ({self.scrap_rate}%)'


class ShelfSlot(models.Model):
    shelf_id = models.CharField(max_length=20)
    slot_index = models.IntegerField()
    is_occupied = models.BooleanField(default=False)
    warehouse = models.ForeignKey('Warehouse', null=True, blank=True, on_delete=models.CASCADE, related_name='shelf_slots')
    delivery = models.ForeignKey(Delivery, null=True, blank=True, on_delete=models.SET_NULL, related_name='slots')
    manufacturing_order = models.ForeignKey('ManufacturingOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='shelf_slots')
    stored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('warehouse', 'shelf_id', 'slot_index')
        ordering = ['shelf_id', 'slot_index']

    def __str__(self):
        status = 'occupied' if self.is_occupied else 'empty'
        return f'{self.shelf_id} slot {self.slot_index} ({status})'


class WarehouseCell(models.Model):
    CELL_TYPE_CHOICES = [
        ('storage', 'Storage Unit'),
        ('wall', 'Wall'),
        ('walkway', 'Walkway'),
        ('dock', 'Loading Dock'),
        ('empty', 'Empty Space'),
    ]
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='cells')
    row = models.IntegerField()
    col = models.IntegerField()
    cell_type = models.CharField(max_length=20, choices=CELL_TYPE_CHOICES, default='empty')
    label = models.CharField(max_length=50, blank=True, default='')
    sector = models.IntegerField(null=True, blank=True)
    unit = models.CharField(max_length=5, blank=True, default='')

    class Meta:
        unique_together = ('warehouse', 'row', 'col')
        ordering = ['row', 'col']

    def __str__(self):
        return f'({self.row},{self.col}) {self.cell_type}'


class GlobalLog(models.Model):
    EVENT_TYPE_CHOICES = [
        ('delivery', 'Delivery'),
        ('manufacturing', 'Manufacturing'),
        ('scrap', 'Scrap'),
        ('machine', 'Machine'),
        ('material', 'Material'),
        ('warehouse', 'Warehouse'),
        ('shipment', 'Shipment'),
        ('threshold', 'Threshold'),
    ]
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES, db_index=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='info', db_index=True)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default='')

    delivery = models.ForeignKey('Delivery', null=True, blank=True, on_delete=models.SET_NULL, related_name='logs')
    manufacturing_order = models.ForeignKey('ManufacturingOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='logs')
    machine = models.ForeignKey('MachineHealth', null=True, blank=True, on_delete=models.SET_NULL, related_name='logs')
    scrap_event = models.ForeignKey('ScrapEvent', null=True, blank=True, on_delete=models.SET_NULL, related_name='logs')

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'event_type']),
            models.Index(fields=['-timestamp', 'severity']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title} ({self.timestamp:%Y-%m-%d %H:%M})'


class AISettings(models.Model):
    """Singleton model for AI configuration (Vertex AI credentials)."""
    gcp_project_id = models.CharField(max_length=200, blank=True, default='')
    gcp_region = models.CharField(max_length=50, default='us-east5')
    service_account_json = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'AI Settings'
        verbose_name_plural = 'AI Settings'

    def __str__(self):
        return f'AI Settings (project: {self.gcp_project_id or "not configured"})'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MaintenanceEntry(models.Model):
    MAINTENANCE_TYPE_CHOICES = [
        ('preventive', 'Preventive'),
        ('corrective', 'Corrective'),
        ('inspection', 'Inspection'),
    ]

    machine = models.ForeignKey(MachineHealth, on_delete=models.CASCADE, related_name='maintenance_entries')
    date = models.DateField()
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPE_CHOICES)
    description = models.TextField()
    parts_replaced = models.TextField(blank=True, default='')
    technician_notes = models.TextField(blank=True, default='')
    next_scheduled = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.machine.machine_name} — {self.maintenance_type} on {self.date}'


class ChatConversation(models.Model):
    session_key = models.CharField(max_length=40, db_index=True)
    title = models.CharField(max_length=200, default='New Conversation')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'Chat {self.id} — {self.title}'


class ChatMessage(models.Model):
    ROLE_CHOICES = [('user', 'User'), ('assistant', 'Assistant')]

    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    tool_calls = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.role}: {self.content[:50]}'
