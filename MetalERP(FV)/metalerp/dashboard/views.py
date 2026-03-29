import json
import random
import uuid
from datetime import datetime, timedelta
from datetime import date, datetime, timedelta
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.db import models
from django.db.models import Count
from django.utils import timezone
from .models import Warehouse, Material, Delivery, ShelfSlot, WarehouseCell, ManufacturingOrder, MachineHealth, ScrapEvent, GlobalLog, AISettings, MaintenanceEntry
import math
from django.views.decorators.csrf import csrf_exempt


def log_event(event_type, severity, title, description='', **kwargs):
    """Create a GlobalLog entry. kwargs can include delivery, manufacturing_order, machine, scrap_event."""
    fk_fields = {'delivery', 'manufacturing_order', 'machine', 'scrap_event'}
    fk_kwargs = {k: v for k, v in kwargs.items() if k in fk_fields}
    GlobalLog.objects.create(
        event_type=event_type,
        severity=severity,
        title=title,
        description=description,
        **fk_kwargs,
    )


# =============================================
# Warehouse Hierarchy Constants (legacy defaults)
# =============================================
SECTORS = list(range(1, 8))           # Sectors 1-7
UNITS = ['A', 'B', 'C', 'D']         # Units per sector
SHELVES_PER_UNIT = 6                  # Shelves per unit
SLOTS_PER_SHELF = 4                   # 1 row x 4 cols


def _get_warehouse_config(warehouse):
    """Return warehouse layout config. Uses DB values if configured, else legacy defaults."""
    if warehouse and warehouse.layout_configured:
        # Build sectors/units from WarehouseCell storage cells
        cells = WarehouseCell.objects.filter(warehouse=warehouse, cell_type='storage')
        sectors_set = set()
        units_set = set()
        for c in cells:
            if c.sector is not None:
                sectors_set.add(c.sector)
                if c.unit:
                    units_set.add(c.unit)
        sectors = sorted(sectors_set) if sectors_set else SECTORS
        units = sorted(units_set) if units_set else UNITS
        return {
            'sectors': sectors,
            'units': units,
            'shelves_per_unit': warehouse.shelves_per_unit,
            'slots_per_shelf': warehouse.slots_per_shelf,
        }
    return {
        'sectors': SECTORS,
        'units': UNITS,
        'shelves_per_unit': SHELVES_PER_UNIT,
        'slots_per_shelf': SLOTS_PER_SHELF,
    }


def _get_current_warehouse(request):
    """Get the current warehouse from session, defaulting to the first one."""
    warehouse_id = request.session.get('current_warehouse_id')
    if warehouse_id:
        try:
            return Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            pass
    wh = Warehouse.objects.first()
    if wh:
        request.session['current_warehouse_id'] = wh.id
    return wh


def _warehouse_context(request):
    """Return common warehouse context for templates."""
    warehouse = _get_current_warehouse(request)
    warehouses = list(Warehouse.objects.all().order_by('id'))
    return warehouse, {
        'warehouses': warehouses,
        'current_warehouse': warehouse,
        'dock_range': list(range(1, (warehouse.num_docks if warehouse else 3) + 1)),
    }

# Delivery generation data
MANUFACTURERS = [
    'Tata Steel Ltd.', 'JSW Steel', 'SAIL', 'Hindalco Industries',
    'Vedanta Resources', 'Jindal Stainless',
]
MATERIAL_SIZES = [
    '2.5mm x 1250mm', '1.2mm x 1000mm', '12mm dia', '3mm x 1500mm',
    '25kg blocks', '0.5mm x 1250mm', '2mm x 1220mm', '8mm dia',
    '50x50x6mm', '10mm x 2000mm', '1.6mm x 1250mm', '50kg blocks',
    '0.8mm x 1000mm', '1.5mm x 1220mm', '16mm dia', '6mm x 2000mm',
    '4mm x 1500mm', '3.15mm x 1250mm',
]


def _get_shelf_capacity(shelf_id, warehouse=None):
    cfg = _get_warehouse_config(warehouse)
    slots_per_shelf = cfg['slots_per_shelf']
    qs = ShelfSlot.objects.filter(shelf_id=shelf_id, is_occupied=True)
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    slots = qs.select_related('delivery', 'manufacturing_order')
    occupied_slots = sorted([s.slot_index for s in slots])
    occupied_count = len(occupied_slots)
    percentage = round(occupied_count / slots_per_shelf * 100) if slots_per_shelf > 0 else 0
    available = [i for i in range(slots_per_shelf) if i not in occupied_slots]

    # Track recently stored slots (within last 5 minutes)
    recent_cutoff = timezone.now() - timedelta(minutes=5)
    recently_stored = []
    # Track finished goods slots (manufacturing_order set, not delivery)
    finished_slots = []
    for s in slots:
        if s.stored_at and s.stored_at >= recent_cutoff:
            recently_stored.append(s.slot_index)
        if s.manufacturing_order_id:
            finished_slots.append(s.slot_index)

    return {
        'total_slots': slots_per_shelf,
        'occupied_slots': occupied_slots,
        'occupied_count': occupied_count,
        'percentage': percentage,
        'next_available': available[0] if available else None,
        'recently_stored': recently_stored,
        'finished_slots': finished_slots,
    }


def _overall_utilization(warehouse=None):
    cfg = _get_warehouse_config(warehouse)
    total_slots = len(cfg['sectors']) * len(cfg['units']) * cfg['shelves_per_unit'] * cfg['slots_per_shelf']
    qs = ShelfSlot.objects.filter(is_occupied=True)
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    occupied = qs.count()
    return round(occupied / total_slots * 100, 1) if total_slots > 0 else 0


# =============================================
# API Endpoints
# =============================================

@require_GET
def shelf_info(request):
    shelf_id = request.GET.get('shelf_id', '')
    if not shelf_id:
        return JsonResponse({'error': 'shelf_id required'}, status=400)
    parts = shelf_id.split('-')
    if len(parts) != 3:
        return JsonResponse({'error': 'Invalid shelf_id format. Use Sector-Unit-Shelf (e.g. 3-B-2)'}, status=400)

    # Allow explicit warehouse_id param (for finished goods store flow)
    wh_id = request.GET.get('warehouse_id')
    if wh_id:
        warehouse = Warehouse.objects.filter(id=int(wh_id)).first()
    else:
        warehouse = _get_current_warehouse(request)
    sector, unit, target_shelf = parts[0], parts[1], parts[2]
    cap = _get_shelf_capacity(shelf_id, warehouse)

    # Also return data for ALL levels in this rack (sector-unit)
    cfg = _get_warehouse_config(warehouse)
    all_levels = {}
    for level in range(1, cfg['shelves_per_unit'] + 1):
        level_id = f'{sector}-{unit}-{level}'
        level_cap = _get_shelf_capacity(level_id, warehouse)
        all_levels[str(level)] = {
            'shelf_id': level_id,
            'occupied_slots': level_cap['occupied_slots'],
            'recently_stored': level_cap['recently_stored'],
            'percentage': level_cap['percentage'],
            'next_available': level_cap['next_available'],
        }

    # Check if there are pending deliveries for this shelf
    pending_qs = Delivery.objects.filter(shelf_id=shelf_id, status='pending')
    if warehouse:
        pending_qs = pending_qs.filter(warehouse=warehouse)
    pending_delivery = pending_qs.first()
    has_pending = pending_delivery is not None
    next_available_shelf = None
    if cap['next_available'] is None and has_pending:
        next_available_shelf = _find_next_shelf_in_rack(sector, unit, int(target_shelf), warehouse)

    # Pallet progress for the pending delivery
    pending_delivery_id = None
    pallets_stored = 0
    pallets_needed = 0
    if pending_delivery:
        pending_delivery_id = pending_delivery.id
        pallets_stored = ShelfSlot.objects.filter(delivery=pending_delivery, is_occupied=True).count()
        try:
            pallets_needed = int(''.join(c for c in pending_delivery.quantity if c.isdigit()))
        except (ValueError, IndexError):
            pallets_needed = 1

    return JsonResponse({
        'shelf_id': shelf_id,
        'sector': sector,
        'unit': unit,
        'shelf': target_shelf,
        'all_levels': all_levels,
        'shelves_per_unit': cfg['shelves_per_unit'],
        'slots_per_shelf': cfg['slots_per_shelf'],
        'has_pending_delivery': has_pending,
        'next_available_shelf': next_available_shelf,
        'pending_delivery_id': pending_delivery_id,
        'pallets_stored': pallets_stored,
        'pallets_needed': pallets_needed,
        **cap,
    })


@csrf_exempt
@require_POST
def mark_stored(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    shelf_id = data.get('shelf_id', '')
    slot_index = data.get('slot_index')
    if not shelf_id or slot_index is None:
        return JsonResponse({'error': 'shelf_id and slot_index required'}, status=400)

    warehouse = _get_current_warehouse(request)
    slot_index = int(slot_index)
    delivery_id = data.get('delivery_id')

    # Find the delivery to link
    delivery_obj = None
    if delivery_id:
        try:
            delivery_obj = Delivery.objects.get(id=int(delivery_id))
        except (Delivery.DoesNotExist, ValueError):
            pass
    else:
        # Auto-find a pending delivery for this shelf
        qs = Delivery.objects.filter(shelf_id=shelf_id, status='pending')
        if warehouse:
            qs = qs.filter(warehouse=warehouse)
        delivery_obj = qs.first()

    # Prevent over-storing: if delivery already has enough pallets stored, reject
    if delivery_obj:
        already_stored = ShelfSlot.objects.filter(delivery=delivery_obj, is_occupied=True).count()
        try:
            needed = int(''.join(c for c in delivery_obj.quantity if c.isdigit()))
        except (ValueError, IndexError):
            needed = 1
        if already_stored >= needed:
            return JsonResponse({'error': 'All pallets for this delivery are already stored'}, status=400)

    slot, _ = ShelfSlot.objects.update_or_create(
        shelf_id=shelf_id, slot_index=slot_index, warehouse=warehouse,
        defaults={
            'is_occupied': True,
            'delivery': delivery_obj,
            'stored_at': timezone.now(),
        }
    )

    # Check how many pallets stored vs quantity for this delivery
    pallets_stored = 0
    pallets_needed = 0
    if delivery_obj:
        pallets_stored = ShelfSlot.objects.filter(delivery=delivery_obj, is_occupied=True).count()
        try:
            pallets_needed = int(''.join(c for c in delivery_obj.quantity if c.isdigit()))
        except (ValueError, IndexError):
            pallets_needed = 1
        # Mark delivery as stored only when all pallets are placed
        if pallets_stored >= pallets_needed and delivery_obj.status == 'pending':
            delivery_obj.status = 'stored'
            delivery_obj.save()
            log_event('shipment', 'info', f'Delivery stored: {delivery_obj.batch_id}',
                      f'All pallets placed on shelf {shelf_id}', delivery=delivery_obj)

    cap = _get_shelf_capacity(shelf_id, warehouse)

    # Multi-shelf overflow: if this shelf is now full but delivery still has unplaced pallets,
    # find the next available shelf for continuation
    overflow_shelf = None
    overflow_next_slot = None
    remaining_pallets = max(0, pallets_needed - pallets_stored)
    if cap['next_available'] is None and remaining_pallets > 0 and delivery_obj:
        # Current shelf is full, find next shelf
        next_shelf_id = _find_available_shelf(needed=remaining_pallets, warehouse=warehouse)
        if next_shelf_id and next_shelf_id != shelf_id:
            next_cap = _get_shelf_capacity(next_shelf_id)
            if next_cap['next_available'] is not None:
                overflow_shelf = next_shelf_id
                overflow_next_slot = next_cap['next_available']
                # Update the delivery's shelf_id to the new shelf for future lookups
                delivery_obj.shelf_id = next_shelf_id
                delivery_obj.save()

    return JsonResponse({
        'shelf_id': shelf_id,
        'stored_slot': slot_index,
        'pallets_stored': pallets_stored,
        'pallets_needed': pallets_needed,
        'overflow_shelf': overflow_shelf,
        'overflow_next_slot': overflow_next_slot,
        'remaining_pallets': remaining_pallets,
        **cap,
    })


@require_GET
def generate_delivery(request):
    warehouse = _get_current_warehouse(request)
    manufacturer = random.choice(MANUFACTURERS)
    prefix = ''.join([w[0] for w in manufacturer.split()[:2]]).upper()
    batch_id = f'BATCH-{prefix}-{random.randint(1000, 9999)}-{uuid.uuid4().hex[:4]}'
    size = random.choice(MATERIAL_SIZES)

    # Find best shelf and cap quantity to what fits
    shelf_id = _find_available_shelf(warehouse=warehouse)
    cfg = _get_warehouse_config(warehouse)
    shelf_qs = ShelfSlot.objects.filter(shelf_id=shelf_id, is_occupied=True)
    if warehouse:
        shelf_qs = shelf_qs.filter(warehouse=warehouse)
    shelf_free = cfg['slots_per_shelf'] - shelf_qs.count()
    max_qty = min(4, max(1, shelf_free))
    quantity = str(random.randint(1, max_qty))

    # Pick a random material
    material = Material.objects.order_by('?').first()
    material_id = material.id if material else None
    material_name = material.name if material else ''

    return JsonResponse({
        'manufacturer': manufacturer,
        'date': str(date.today()),
        'size': size,
        'batch_id': batch_id,
        'quantity': quantity,
        'shelf_id': shelf_id,
        'material_id': material_id,
        'material_name': material_name,
    })


def _find_available_shelf(needed=1, warehouse=None):
    """Find a shelf that can fit `needed` pallets. Returns shelf with most space."""
    cfg = _get_warehouse_config(warehouse)
    sectors = cfg['sectors']
    units = cfg['units']
    shelves_per_unit = cfg['shelves_per_unit']
    slots_per_shelf = cfg['slots_per_shelf']

    all_shelves = []
    for s in sectors:
        for u in units:
            for sh in range(1, shelves_per_unit + 1):
                all_shelves.append(f'{s}-{u}-{sh}')

    # Get occupancy counts in one query
    occupied_counts = {}
    qs = ShelfSlot.objects.filter(is_occupied=True)
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    for slot in qs.values('shelf_id').annotate(count=Count('id')):
        occupied_counts[slot['shelf_id']] = slot['count']

    # Find shelf with most free space that can fit at least 1 pallet
    best_shelf = None
    best_free = 0
    random.shuffle(all_shelves)  # randomize among equal candidates
    for shelf_id in all_shelves:
        occupied = occupied_counts.get(shelf_id, 0)
        free = slots_per_shelf - occupied
        if free > best_free:
            best_free = free
            best_shelf = shelf_id

    if best_shelf:
        return best_shelf

    # Fallback
    s = random.choice(sectors) if sectors else 1
    u = random.choice(units) if units else 'A'
    sh = random.randint(1, shelves_per_unit)
    return f'{s}-{u}-{sh}'


def _find_next_shelf_in_rack(sector, unit, current_shelf, warehouse=None):
    """Find the next available shelf in the same rack, then fallback to any shelf."""
    cfg = _get_warehouse_config(warehouse)
    shelves_per_unit = cfg['shelves_per_unit']
    for sh in list(range(current_shelf + 1, shelves_per_unit + 1)) + list(range(1, current_shelf)):
        sid = f'{sector}-{unit}-{sh}'
        cap = _get_shelf_capacity(sid, warehouse)
        if cap['next_available'] is not None:
            return sid
    return _find_available_shelf(warehouse=warehouse)


def _total_available_slots(warehouse=None):
    """Return total number of free slots across the entire warehouse."""
    cfg = _get_warehouse_config(warehouse)
    total = len(cfg['sectors']) * len(cfg['units']) * cfg['shelves_per_unit'] * cfg['slots_per_shelf']
    qs = ShelfSlot.objects.filter(is_occupied=True)
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    occupied = qs.count()
    return total - occupied


@require_POST
def add_delivery(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    required = ['manufacturer', 'date', 'size', 'batch_id', 'quantity', 'shelf_id']
    for field in required:
        if field not in data or not data[field]:
            return JsonResponse({'error': f'{field} is required'}, status=400)

    warehouse = _get_current_warehouse(request)

    # Link material if provided
    material = None
    material_id_input = data.get('material_id')
    if material_id_input:
        try:
            material = Material.objects.get(id=int(material_id_input))
        except (Material.DoesNotExist, ValueError):
            pass

    delivery = Delivery.objects.create(
        manufacturer=data['manufacturer'],
        date=data['date'],
        size=data['size'],
        batch_id=data['batch_id'],
        quantity=data['quantity'],
        shelf_id=data['shelf_id'],
        status='pending',
        material=material,
        warehouse=warehouse,
    )
    log_event('delivery', 'info', f'Delivery added: {delivery.batch_id}',
              f'From {delivery.manufacturer}, qty {delivery.quantity}, shelf {delivery.shelf_id}',
              delivery=delivery)

    return JsonResponse({
        'id': delivery.id,
        'manufacturer': delivery.manufacturer,
        'date': str(delivery.date),
        'created_at': delivery.created_at.strftime('%b %d, %I:%M %p'),
        'size': delivery.size,
        'batch_id': delivery.batch_id,
        'quantity': delivery.quantity,
        'shelf_id': delivery.shelf_id,
        'status': delivery.status,
        'material_id': delivery.material.id if delivery.material else None,
        'material_name': delivery.material.name if delivery.material else '',
    })


@require_GET
def warehouse_map(request):
    """Return occupancy data for every shelf in the warehouse."""
    # Allow explicit warehouse_id param (for finished goods store flow)
    wh_id = request.GET.get('warehouse_id')
    if wh_id:
        warehouse = Warehouse.objects.filter(id=int(wh_id)).first()
    else:
        warehouse = _get_current_warehouse(request)
    slot_qs = ShelfSlot.objects.filter(is_occupied=True)
    delivery_qs = Delivery.objects.filter(status='pending')
    if warehouse:
        slot_qs = slot_qs.filter(warehouse=warehouse)
        delivery_qs = delivery_qs.filter(warehouse=warehouse)

    all_occupied = {}
    for slot in slot_qs.values('shelf_id').annotate(count=Count('id')):
        all_occupied[slot['shelf_id']] = slot['count']

    # Pending deliveries by shelf
    pending_shelves = set(
        delivery_qs.values_list('shelf_id', flat=True)
    )

    cfg = _get_warehouse_config(warehouse)

    sectors = {}
    for s in cfg['sectors']:
        units_data = {}
        for u in cfg['units']:
            shelves = {}
            for sh in range(1, cfg['shelves_per_unit'] + 1):
                shelf_id = f'{s}-{u}-{sh}'
                occupied = all_occupied.get(shelf_id, 0)
                has_pending = shelf_id in pending_shelves
                if occupied >= cfg['slots_per_shelf']:
                    status = 'full'
                elif has_pending or occupied > 0:
                    status = 'partial'
                else:
                    status = 'empty'
                shelves[str(sh)] = {
                    'occupied': occupied,
                    'total': cfg['slots_per_shelf'],
                    'status': status,
                }
            units_data[u] = shelves
        sectors[str(s)] = units_data

    # Include layout data if warehouse has a configured layout
    layout = None
    if warehouse and warehouse.layout_configured:
        cells = WarehouseCell.objects.filter(warehouse=warehouse).order_by('row', 'col')
        cell_list = []
        for c in cells:
            cell_data = {
                'row': c.row, 'col': c.col, 'cell_type': c.cell_type,
                'label': c.label, 'sector': c.sector, 'unit': c.unit,
            }
            if c.cell_type == 'storage' and c.sector is not None and c.unit:
                # Aggregate occupancy for this storage cell
                total_occ = 0
                total_cap = cfg['shelves_per_unit'] * cfg['slots_per_shelf']
                for sh in range(1, cfg['shelves_per_unit'] + 1):
                    sid = f'{c.sector}-{c.unit}-{sh}'
                    total_occ += all_occupied.get(sid, 0)
                if total_occ >= total_cap:
                    cell_data['status'] = 'full'
                elif total_occ > 0:
                    cell_data['status'] = 'partial'
                else:
                    cell_data['status'] = 'empty'
                cell_data['occupied'] = total_occ
                cell_data['total'] = total_cap
            cell_list.append(cell_data)
        layout = {
            'grid_rows': warehouse.grid_rows,
            'grid_cols': warehouse.grid_cols,
            'width_m': warehouse.width_m,
            'length_m': warehouse.length_m,
            'height_m': warehouse.height_m,
            'shape': warehouse.shape,
            'cells': cell_list,
        }

    return JsonResponse({
        'sectors': sectors,
        'layout': layout,
        'shelves_per_unit': cfg['shelves_per_unit'],
        'slots_per_shelf': cfg['slots_per_shelf'],
    })


@require_GET
def delivery_statuses(request):
    """Lightweight endpoint for real-time row updates."""
    warehouse = _get_current_warehouse(request)
    d_qs = Delivery.objects.filter(status__in=['pending', 'stored'])
    s_qs = ShelfSlot.objects.filter(is_occupied=True, delivery__isnull=False)
    if warehouse:
        d_qs = d_qs.filter(warehouse=warehouse)
        s_qs = s_qs.filter(warehouse=warehouse)

    deliveries = d_qs.values('id', 'status', 'shelf_id')
    all_occupied = {}
    for slot in s_qs.values('shelf_id').annotate(count=Count('id')):
        all_occupied[slot['shelf_id']] = slot['count']
    cfg = _get_warehouse_config(warehouse)
    result = {}
    for d in deliveries:
        occ = all_occupied.get(d['shelf_id'], 0)
        result[str(d['id'])] = {
            'status': d['status'],
            'shelf_id': d['shelf_id'],
            'shelf_occupied': occ,
            'shelf_full': occ >= cfg['slots_per_shelf'],
        }
    total = len(cfg['sectors']) * len(cfg['units']) * cfg['shelves_per_unit'] * cfg['slots_per_shelf']
    occupied = s_qs.count()
    pending_qs = Delivery.objects.filter(status='pending')
    stored_qs = Delivery.objects.filter(status='stored')
    if warehouse:
        pending_qs = pending_qs.filter(warehouse=warehouse)
        stored_qs = stored_qs.filter(warehouse=warehouse)
    return JsonResponse({
        'deliveries': result,
        'pending_count': pending_qs.count(),
        'stored_count': stored_qs.count(),
        'occupied_slots': occupied,
        'total_slots': total,
    })


@require_POST
def delete_delivery(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    delivery_id = data.get('delivery_id')
    if not delivery_id:
        return JsonResponse({'error': 'delivery_id required'}, status=400)
    delete_reason = data.get('delete_reason', '')
    try:
        d = Delivery.objects.get(id=int(delivery_id))
    except (Delivery.DoesNotExist, ValueError):
        return JsonResponse({'error': 'Delivery not found'}, status=404)
    # Delete all shelf slots linked to this delivery (frees shelf space)
    ShelfSlot.objects.filter(delivery=d).delete()
    # Soft delete — mark as deleted with reason
    d.status = 'deleted'
    d.delete_reason = delete_reason
    d.save(update_fields=['status', 'delete_reason'])
    log_event('delivery', 'warning', f'Delivery deleted: {d.batch_id}',
              f'Reason: {delete_reason or "No reason given"}', delivery=d)
    return JsonResponse({'success': True, 'id': int(delivery_id)})


@require_GET
def deleted_deliveries(request):
    warehouse = _get_current_warehouse(request)
    qs = Delivery.objects.filter(status='deleted').select_related('material')
    if warehouse:
        qs = qs.filter(warehouse=warehouse)
    deliveries = qs.order_by('-id')
    result = []
    for d in deliveries:
        result.append({
            'id': d.id,
            'manufacturer': d.manufacturer,
            'date': str(d.date),
            'size': d.size,
            'batch_id': d.batch_id,
            'quantity': d.quantity,
            'shelf_id': d.shelf_id,
            'delete_reason': d.delete_reason,
            'material_name': d.material.name if d.material else '',
        })
    return JsonResponse({'deliveries': result})


@require_GET
def warehouse_stats(request):
    """Return overall warehouse capacity stats."""
    warehouse = _get_current_warehouse(request)
    cfg = _get_warehouse_config(warehouse)
    total = len(cfg['sectors']) * len(cfg['units']) * cfg['shelves_per_unit'] * cfg['slots_per_shelf']
    s_qs = ShelfSlot.objects.filter(is_occupied=True)
    p_qs = Delivery.objects.filter(status='pending')
    st_qs = Delivery.objects.filter(status='stored')
    if warehouse:
        s_qs = s_qs.filter(warehouse=warehouse)
        p_qs = p_qs.filter(warehouse=warehouse)
        st_qs = st_qs.filter(warehouse=warehouse)
    occupied = s_qs.count()
    pending = p_qs.count()
    stored = st_qs.count()
    return JsonResponse({
        'total_slots': total,
        'occupied_slots': occupied,
        'available_slots': total - occupied,
        'pending_deliveries': pending,
        'stored_deliveries': stored,
        'total_deliveries': pending + stored,
    })


# =============================================
# Warehouse Layout APIs
# =============================================

@require_GET
def warehouse_layout(request, warehouse_id):
    """Return full grid layout for a warehouse."""
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)
    cells = WarehouseCell.objects.filter(warehouse=wh).order_by('row', 'col')
    cell_list = [
        {'row': c.row, 'col': c.col, 'cell_type': c.cell_type,
         'label': c.label, 'sector': c.sector, 'unit': c.unit}
        for c in cells
    ]
    return JsonResponse({
        'id': wh.id,
        'name': wh.name,
        'shape': wh.shape,
        'width_m': wh.width_m,
        'length_m': wh.length_m,
        'height_m': wh.height_m,
        'grid_rows': wh.grid_rows,
        'grid_cols': wh.grid_cols,
        'shelves_per_unit': wh.shelves_per_unit,
        'slots_per_shelf': wh.slots_per_shelf,
        'layout_configured': wh.layout_configured,
        'cells': cell_list,
    })


@require_POST
def warehouse_layout_save(request, warehouse_id):
    """Bulk save warehouse layout dimensions and cells."""
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Update warehouse dimensions
    wh.shape = data.get('shape', wh.shape)
    wh.width_m = float(data.get('width_m', wh.width_m))
    wh.length_m = float(data.get('length_m', wh.length_m))
    wh.height_m = float(data.get('height_m', wh.height_m))
    wh.grid_rows = int(data.get('grid_rows', wh.grid_rows))
    wh.grid_cols = int(data.get('grid_cols', wh.grid_cols))
    wh.shelves_per_unit = int(data.get('shelves_per_unit', wh.shelves_per_unit))
    wh.slots_per_shelf = int(data.get('slots_per_shelf', wh.slots_per_shelf))
    wh.layout_configured = True
    wh.save()

    # Bulk upsert cells
    cells_data = data.get('cells', [])
    if cells_data:
        WarehouseCell.objects.filter(warehouse=wh).delete()
        objs = [
            WarehouseCell(
                warehouse=wh,
                row=c['row'], col=c['col'],
                cell_type=c.get('cell_type', 'empty'),
                label=c.get('label', ''),
                sector=c.get('sector'),
                unit=c.get('unit', ''),
            )
            for c in cells_data
        ]
        WarehouseCell.objects.bulk_create(objs)

    log_event('warehouse', 'info', f'Warehouse layout saved: {wh.name}',
              f'{wh.grid_rows}x{wh.grid_cols} grid, shape={wh.shape}')
    return JsonResponse({'success': True, 'id': wh.id})


@require_POST
def warehouse_apply_shape(request, warehouse_id):
    """Preview shape template — returns cell grid without saving."""
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    shape = data.get('shape', 'rectangle')
    rows = int(data.get('grid_rows', wh.grid_rows))
    cols = int(data.get('grid_cols', wh.grid_cols))

    cells = []
    center_r = (rows - 1) / 2.0
    center_c = (cols - 1) / 2.0
    radius_r = rows / 2.0
    radius_c = cols / 2.0

    for r in range(rows):
        for c in range(cols):
            if shape == 'circle':
                dist = ((r - center_r) / radius_r) ** 2 + ((c - center_c) / radius_c) ** 2
                cell_type = 'wall' if dist > 1.0 else 'empty'
            else:
                cell_type = 'empty'
            cells.append({'row': r, 'col': c, 'cell_type': cell_type,
                          'label': '', 'sector': None, 'unit': ''})

    return JsonResponse({'cells': cells, 'grid_rows': rows, 'grid_cols': cols})


@require_POST
def warehouse_toggle_cell(request, warehouse_id):
    """Toggle a single cell's type."""
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    row = int(data['row'])
    col = int(data['col'])
    cell_type = data.get('cell_type', 'wall')

    cell, created = WarehouseCell.objects.update_or_create(
        warehouse=wh, row=row, col=col,
        defaults={'cell_type': cell_type}
    )
    return JsonResponse({'row': row, 'col': col, 'cell_type': cell.cell_type})


@require_POST
def warehouse_auto_assign(request, warehouse_id):
    """Auto-number storage cells as sectors and units."""
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)

    cells = list(WarehouseCell.objects.filter(
        warehouse=wh, cell_type='storage'
    ).order_by('row', 'col'))

    if not cells:
        return JsonResponse({'error': 'No storage cells to assign'}, status=400)

    # Simple assignment: each storage cell gets a unique sector-unit pair
    unit_labels = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    sector = 1
    unit_idx = 0
    for cell in cells:
        cell.sector = sector
        cell.unit = unit_labels[unit_idx]
        cell.label = f'S{sector}-{unit_labels[unit_idx]}'
        unit_idx += 1
        if unit_idx >= len(unit_labels):
            unit_idx = 0
            sector += 1

    WarehouseCell.objects.bulk_update(cells, ['sector', 'unit', 'label'])

    cell_list = [
        {'row': c.row, 'col': c.col, 'cell_type': c.cell_type,
         'label': c.label, 'sector': c.sector, 'unit': c.unit}
        for c in cells
    ]
    return JsonResponse({'success': True, 'cells': cell_list})


def warehouse_setup(request, warehouse_id):
    """Render the warehouse layout setup page."""
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        from django.http import Http404
        raise Http404
    warehouse, wh_ctx = _warehouse_context(request)
    context = {
        'active_tab': 'settings',
        'setup_warehouse': wh,
        **wh_ctx,
    }
    return render(request, 'dashboard/warehouse_setup.html', context)


# =============================================
# Page Views
# =============================================

def index(request):
    warehouse, wh_ctx = _warehouse_context(request)
    p_qs = Delivery.objects.filter(status='pending')
    if warehouse:
        p_qs = p_qs.filter(warehouse=warehouse)
    context = {
        'active_tab': 'dashboard',
        'today': date.today().strftime('%d %B %Y'),
        'stats': {
            'total_materials': Material.objects.count(),
            'pending_deliveries': p_qs.count(),
            'completed_orders': ManufacturingOrder.objects.filter(status='completed').count(),
            'total_orders': ManufacturingOrder.objects.count(),
            'defected_orders': ManufacturingOrder.objects.filter(status='defected').count(),
            'storage_utilization': _overall_utilization(warehouse),
        },
        **wh_ctx,
    }
    recent = list(ManufacturingOrder.objects.values(
        'order_id', 'product', 'dimensions', 'material_name', 'delivery_batch',
        'manufacturer', 'status', 'processing_time', 'total_energy', 'total_scrap',
        'quality', 'defect_machine', 'defect_machine_id', 'defect_type', 'defect_cause',
        'stages_completed', 'stage_data', 'stage_timestamps', 'created_at',
    )[:10])
    for r in recent:
        r['created_at'] = r['created_at'].strftime('%b %d, %I:%M %p') if r['created_at'] else ''
    context['recent_orders'] = recent
    context['recent_orders_json'] = json.dumps(recent)

    # Load scrap events for recent orders
    recent_order_ids = [r['order_id'] for r in recent]
    recent_scraps = list(ScrapEvent.objects.filter(
        order__order_id__in=recent_order_ids
    ).values(
        'order__order_id', 'machine_name', 'machine_id', 'machine_index',
        'scrap_type', 'scrap_rate', 'material_name', 'delivery_batch', 'created_at',
    ))
    for s in recent_scraps:
        s['order_id'] = s.pop('order__order_id', '')
        s['created_at'] = s['created_at'].strftime('%I:%M:%S %p') if s['created_at'] else ''
    context['recent_scraps_json'] = json.dumps(recent_scraps)

    # Machine specs for timeline rendering
    _ensure_machine_records()
    health_machines = MachineHealth.objects.all().order_by('position')
    machine_names = []
    for hm in health_machines:
        machine_names.append({'name': hm.machine_name, 'id': hm.machine_id})
    context['machine_names_json'] = json.dumps(machine_names)

    # Orders timeline data for scatter chart
    all_orders = list(ManufacturingOrder.objects.values(
        'order_id', 'quality', 'status', 'created_at', 'product',
        'defect_machine', 'defect_type',
    ).order_by('created_at')[:50])
    for o in all_orders:
        o['created_at_iso'] = o['created_at'].isoformat() if o['created_at'] else ''
        o['created_at'] = o['created_at'].strftime('%b %d, %I:%M %p') if o['created_at'] else ''
    context['timeline_orders_json'] = json.dumps(all_orders)

    return render(request, 'dashboard/index.html', context)


def delivery(request):
    warehouse, wh_ctx = _warehouse_context(request)
    cfg = _get_warehouse_config(warehouse)
    d_qs = Delivery.objects.select_related('material').exclude(status='deleted')
    if warehouse:
        d_qs = d_qs.filter(warehouse=warehouse)
    delivery_list = []
    for d in d_qs:
        slot_qs = ShelfSlot.objects.filter(delivery=d, is_occupied=True)
        pallets_stored = slot_qs.count()
        try:
            pallets_needed = int(''.join(c for c in d.quantity if c.isdigit()))
        except (ValueError, IndexError):
            pallets_needed = 1
        shelf_occ_qs = ShelfSlot.objects.filter(shelf_id=d.shelf_id, is_occupied=True)
        if warehouse:
            shelf_occ_qs = shelf_occ_qs.filter(warehouse=warehouse)
        shelf_occupied = shelf_occ_qs.count()
        delivery_list.append({
            'id': d.id,
            'manufacturer': d.manufacturer,
            'date': str(d.date),
            'created_at': d.created_at.strftime('%b %d, %I:%M %p') if d.created_at else str(d.date),
            'size': d.size,
            'batch_id': d.batch_id,
            'quantity': d.quantity,
            'shelf_id': d.shelf_id,
            'status': d.status,
            'pallets_stored': pallets_stored,
            'pallets_needed': pallets_needed,
            'shelf_occupied': shelf_occupied,
            'shelf_full': shelf_occupied >= cfg['slots_per_shelf'],
            'material_id': d.material.id if d.material else None,
            'material_name': d.material.name if d.material else '',
        })

    total_slots = len(cfg['sectors']) * len(cfg['units']) * cfg['shelves_per_unit'] * cfg['slots_per_shelf']
    occ_qs = ShelfSlot.objects.filter(is_occupied=True, delivery__isnull=False)
    pend_qs = Delivery.objects.filter(status='pending')
    stor_qs = Delivery.objects.filter(status='stored')
    if warehouse:
        occ_qs = occ_qs.filter(warehouse=warehouse)
        pend_qs = pend_qs.filter(warehouse=warehouse)
        stor_qs = stor_qs.filter(warehouse=warehouse)
    occupied_slots = occ_qs.count()

    context = {
        'active_tab': 'delivery',
        'slots_per_shelf': cfg['slots_per_shelf'],
        'deliveries': delivery_list,
        'total_slots': total_slots,
        'occupied_slots': occupied_slots,
        'available_slots': total_slots - occupied_slots,
        'pending_count': pend_qs.count(),
        'stored_count': stor_qs.count(),
        **wh_ctx,
    }
    return render(request, 'dashboard/delivery.html', context)


def _get_manufacturing_context(request, all_warehouses=False):
    """Build common manufacturing pipeline data (materials, deliveries, orders, scraps, machine specs)."""
    warehouse, wh_ctx = _warehouse_context(request)
    materials_list = list(
        Material.objects.values('id', 'name', 'category')
    )
    del_qs = Delivery.objects.filter(status='stored')
    if not all_warehouses and warehouse:
        del_qs = del_qs.filter(warehouse=warehouse)
    deliveries_list = list(
        del_qs.values('id', 'manufacturer', 'batch_id', 'size', 'quantity', 'shelf_id',
                material_name=models.F('material__name'), material_id_ref=models.F('material__id'),
                warehouse_name=models.F('warehouse__name'), warehouse_code=models.F('warehouse__code'))
    )
    for d in deliveries_list:
        d['material_name'] = d.pop('material_name', '') or ''
        d['material_id'] = d.pop('material_id_ref', None)
        d['warehouse_name'] = d.pop('warehouse_name', '') or ''
        d['warehouse_code'] = d.pop('warehouse_code', '') or ''
        try:
            d['qty_int'] = int(''.join(c for c in d['quantity'] if c.isdigit()))
        except (ValueError, IndexError):
            d['qty_int'] = 1
    deliveries_list = [d for d in deliveries_list if d['qty_int'] > 0]

    saved_orders = list(ManufacturingOrder.objects.values(
        'order_id', 'product', 'dimensions', 'material_name', 'delivery_batch',
        'manufacturer', 'status', 'processing_time', 'total_energy', 'total_scrap',
        'quality', 'defect_machine', 'defect_machine_id', 'defect_type', 'defect_cause',
        'stages_completed', 'stage_data', 'stage_timestamps', 'created_at',
    )[:50])
    for o in saved_orders:
        o['created_at'] = o['created_at'].strftime('%I:%M:%S %p') if o['created_at'] else ''

    saved_scraps = list(ScrapEvent.objects.select_related('order').values(
        'order__order_id', 'machine_name', 'machine_id', 'machine_index',
        'scrap_type', 'scrap_rate', 'material_name', 'delivery_batch', 'created_at',
    )[:100])
    for s in saved_scraps:
        s['order_id'] = s.pop('order__order_id', '')
        s['created_at'] = s['created_at'].strftime('%I:%M:%S %p') if s['created_at'] else ''

    _ensure_machine_records()
    health_machines = MachineHealth.objects.all().order_by('position')
    machine_specs = []
    for hm in health_machines:
        dd = hm.detail_data or {}
        pc = dd.get('pipeline_config', MACHINE_PIPELINE_DEFAULTS.get(hm.machine_id, DEFAULT_PIPELINE_CONFIG))
        machine_specs.append({
            'name': hm.machine_name,
            'id': hm.machine_id,
            'visual_type': pc.get('visual_type', 'generic'),
            'metrics': pc.get('metrics', DEFAULT_PIPELINE_CONFIG['metrics']),
            'defect_types': pc.get('defect_types', DEFAULT_PIPELINE_CONFIG['defect_types']),
            'defect_causes': pc.get('defect_causes', DEFAULT_PIPELINE_CONFIG['defect_causes']),
            'scrap_rate': pc.get('scrap_rate', DEFAULT_PIPELINE_CONFIG['scrap_rate']),
            'purchaseDate': dd.get('purchaseDate', ''),
            'depreciationYears': dd.get('depreciationYears', 10),
            'wearLevel': dd.get('wearLevel', 0),
            'totalHours': dd.get('totalHours', 0),
            'partsChanged': dd.get('partsChanged', []),
            'maintenanceLog': dd.get('maintenanceLog', []),
        })

    return {
        'materials_json': json.dumps(materials_list),
        'deliveries_json': json.dumps(deliveries_list),
        'saved_orders_json': json.dumps(saved_orders),
        'saved_scraps_json': json.dumps(saved_scraps),
        'machine_specs_json': json.dumps(machine_specs),
    }


def manufacturing(request):
    context = {
        'active_tab': 'manufacturing',
        **_get_manufacturing_context(request),
    }
    return render(request, 'dashboard/manufacturing.html', context)


@require_POST
def save_manufacturing_order(request):
    """Save a completed or defected manufacturing order."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    order_id = data.get('order_id', '')
    if not order_id:
        return JsonResponse({'error': 'order_id required'}, status=400)

    # Resolve delivery FK if provided
    delivery_obj = None
    delivery_id = data.get('delivery_id')
    if delivery_id:
        try:
            delivery_obj = Delivery.objects.get(id=delivery_id)
        except Delivery.DoesNotExist:
            pass

    # Upsert: update if exists, create otherwise
    obj, created = ManufacturingOrder.objects.update_or_create(
        order_id=order_id,
        defaults={
            'product': data.get('product', ''),
            'dimensions': data.get('dimensions', ''),
            'material_name': data.get('material_name', ''),
            'delivery': delivery_obj,
            'delivery_batch': data.get('delivery_batch', ''),
            'manufacturer': data.get('manufacturer', ''),
            'status': data.get('status', 'completed'),
            'processing_time': float(data.get('processing_time', 0)),
            'total_energy': float(data.get('total_energy', 0)),
            'total_scrap': float(data.get('total_scrap', 0)),
            'quality': data.get('quality', 'PASS'),
            'defect_machine': data.get('defect_machine', ''),
            'defect_machine_id': data.get('defect_machine_id', ''),
            'defect_type': data.get('defect_type', ''),
            'defect_cause': data.get('defect_cause', ''),
            'stages_completed': int(data.get('stages_completed', 5)),
            'stage_data': data.get('stage_data', []),
            'stage_timestamps': data.get('stage_timestamps', []),
        }
    )

    # Log the manufacturing order
    if obj.status == 'defected':
        log_event('manufacturing', 'error', f'Order defected: {obj.order_id}',
                  f'Defect at {obj.defect_machine}: {obj.defect_type} — {obj.defect_cause}',
                  manufacturing_order=obj)
    else:
        log_event('manufacturing', 'info', f'Order completed: {obj.order_id}',
                  f'{obj.product}, {obj.processing_time:.1f}s processing, quality {obj.quality}',
                  manufacturing_order=obj)

    # Save scrap events
    scrap_events = data.get('scrap_events', [])
    if scrap_events:
        for se in scrap_events:
            se_obj = ScrapEvent.objects.create(
                order=obj,
                machine_name=se.get('machine_name', ''),
                machine_id=se.get('machine_id', ''),
                machine_index=int(se.get('machine_index', 0)),
                scrap_type=se.get('scrap_type', ''),
                scrap_rate=float(se.get('scrap_rate', 0)),
                material_name=data.get('material_name', ''),
                delivery_batch=data.get('delivery_batch', ''),
            )
            log_event('scrap', 'warning', f'Scrap at {se_obj.machine_name}',
                      f'Order {obj.order_id}: {se_obj.scrap_type} ({se_obj.scrap_rate:.2f}%)',
                      manufacturing_order=obj, scrap_event=se_obj)

    return JsonResponse({'success': True, 'id': obj.id, 'created': created})


@require_POST
def consume_pallet(request):
    """Consume one pallet from a delivery when a manufacturing order completes."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    delivery_id = data.get('delivery_id')
    if not delivery_id:
        return JsonResponse({'error': 'delivery_id required'}, status=400)

    try:
        delivery = Delivery.objects.get(id=delivery_id)
    except Delivery.DoesNotExist:
        return JsonResponse({'error': 'Delivery not found'}, status=404)

    # Parse current quantity
    try:
        current_qty = int(''.join(c for c in delivery.quantity if c.isdigit()))
    except (ValueError, IndexError):
        current_qty = 0

    if current_qty <= 0:
        return JsonResponse({'error': 'No pallets remaining'}, status=400)

    # Free one shelf slot linked to this delivery
    slot = ShelfSlot.objects.filter(delivery=delivery, is_occupied=True).first()
    if slot:
        slot.is_occupied = False
        slot.delivery = None
        slot.save()

    new_qty = current_qty - 1
    delivery.quantity = str(new_qty)

    if new_qty <= 0:
        # All pallets consumed — mark as deleted
        delivery.status = 'deleted'
        delivery.delete_reason = 'All pallets consumed by manufacturing'
        # Free any remaining slots
        ShelfSlot.objects.filter(delivery=delivery).update(is_occupied=False, delivery=None)
        log_event('delivery', 'warning', f'Delivery fully consumed: {delivery.batch_id}',
                  'All pallets consumed by manufacturing', delivery=delivery)
    else:
        log_event('manufacturing', 'info', f'Pallet consumed from {delivery.batch_id}',
                  f'Remaining: {new_qty}', delivery=delivery)

    delivery.save()
    return JsonResponse({'success': True, 'remaining': new_qty})


@require_POST
def store_finished_order(request):
    """Store a completed manufacturing order on a warehouse shelf slot."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    order_id = data.get('order_id', '')
    warehouse_id = data.get('warehouse_id')
    shelf_id = data.get('shelf_id', '')
    slot_index = data.get('slot_index')

    if not order_id or not warehouse_id or not shelf_id or slot_index is None:
        return JsonResponse({'error': 'order_id, warehouse_id, shelf_id, and slot_index required'}, status=400)

    try:
        order = ManufacturingOrder.objects.get(order_id=order_id)
    except ManufacturingOrder.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

    try:
        warehouse = Warehouse.objects.get(id=int(warehouse_id))
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)

    slot_index = int(slot_index)

    # Create the shelf slot for the finished order
    slot, _ = ShelfSlot.objects.update_or_create(
        shelf_id=shelf_id, slot_index=slot_index, warehouse=warehouse,
        defaults={
            'is_occupied': True,
            'manufacturing_order': order,
            'delivery': None,
            'stored_at': timezone.now(),
        }
    )

    # Build detailed description with full traceability
    desc_parts = [f'{order.product} placed on shelf {shelf_id} slot {slot_index} in {warehouse.name}']
    if order.material_name:
        desc_parts.append(f'Material: {order.material_name}')
    if order.delivery_batch:
        desc_parts.append(f'From batch: {order.delivery_batch}')
    if order.manufacturer:
        desc_parts.append(f'Supplier: {order.manufacturer}')
    if order.delivery and order.delivery.warehouse:
        desc_parts.append(f'Raw material was in: {order.delivery.warehouse.name} shelf {order.delivery.shelf_id}')
    desc_parts.append(f'Quality: {order.quality}, Stages: {order.stages_completed}')
    log_event('warehouse', 'info', f'Finished order stored: {order.order_id}',
              ' | '.join(desc_parts),
              manufacturing_order=order)

    return JsonResponse({
        'success': True,
        'order_id': order.order_id,
        'warehouse': warehouse.name,
        'shelf_id': shelf_id,
        'slot_index': slot_index,
    })


# =============================================
# Machine Health
# =============================================
MACHINE_DEFAULTS = [
    {'machine_id': 'MCH-UL-01', 'machine_name': 'Uncoiler & Leveler', 'failure_threshold': 10, 'position': 0},
    {'machine_id': 'MCH-SC-02', 'machine_name': 'Shearing & Cutting', 'failure_threshold': 10, 'position': 1},
    {'machine_id': 'MCH-PB-03', 'machine_name': 'Press Brake / Bending', 'failure_threshold': 10, 'position': 2},
    {'machine_id': 'MCH-WJ-04', 'machine_name': 'Welding & Joining', 'failure_threshold': 10, 'position': 3},
    {'machine_id': 'MCH-QC-05', 'machine_name': 'Surface Treatment & QC', 'failure_threshold': 10, 'position': 4},
]

MACHINE_DETAIL_DEFAULTS = {
    'MCH-UL-01': {
        'purchaseDate': '2019-06-15', 'depreciationYears': 15, 'wearLevel': 34, 'totalHours': 18420,
        'partsChanged': ['Leveler rollers (2024)', 'Tension sensor (2025)', 'Drive belt (2023)'],
        'maintenanceLog': [
            {'date': '2025-11-20', 'type': 'Preventive', 'desc': 'Leveler roller alignment & calibration', 'cost': 12500},
            {'date': '2025-08-03', 'type': 'Corrective', 'desc': 'Tension sensor replacement', 'cost': 8200},
            {'date': '2024-12-10', 'type': 'Preventive', 'desc': 'Full bearing inspection & lubrication', 'cost': 3800},
        ],
        'resources': [
            {'name': 'Hydraulic Oil', 'level': 82, 'icon': 'droplet'},
            {'name': 'Grease (Bearings)', 'level': 64, 'icon': 'droplet'},
            {'name': 'Coolant', 'level': 91, 'icon': 'thermometer'},
            {'name': 'Drive Belt Tension', 'level': 76, 'icon': 'gauge'},
        ],
    },
    'MCH-SC-02': {
        'purchaseDate': '2020-02-10', 'depreciationYears': 12, 'wearLevel': 28, 'totalHours': 14200,
        'partsChanged': ['Blade set (2025)', 'Hydraulic seals (2025)', 'Guide rails (2024)'],
        'maintenanceLog': [
            {'date': '2026-01-15', 'type': 'Preventive', 'desc': 'Blade sharpening & geometric calibration', 'cost': 5500},
            {'date': '2025-09-22', 'type': 'Corrective', 'desc': 'Hydraulic cylinder seal replacement', 'cost': 18000},
            {'date': '2025-03-14', 'type': 'Preventive', 'desc': 'Lubrication system flush & filter change', 'cost': 2200},
        ],
        'resources': [
            {'name': 'Hydraulic Fluid', 'level': 71, 'icon': 'droplet'},
            {'name': 'Blade Lubricant', 'level': 45, 'icon': 'droplet'},
            {'name': 'Coolant', 'level': 88, 'icon': 'thermometer'},
            {'name': 'Pneumatic Pressure', 'level': 93, 'icon': 'gauge'},
        ],
    },
    'MCH-PB-03': {
        'purchaseDate': '2021-09-01', 'depreciationYears': 20, 'wearLevel': 18, 'totalHours': 10800,
        'partsChanged': ['Die set V-groove 88deg (2025)', 'Ram alignment shims (2026)'],
        'maintenanceLog': [
            {'date': '2026-02-28', 'type': 'Preventive', 'desc': 'Ram alignment & die inspection', 'cost': 7800},
            {'date': '2025-06-18', 'type': 'Preventive', 'desc': 'Hydraulic oil change & pressure test', 'cost': 4200},
        ],
        'resources': [
            {'name': 'Hydraulic Oil', 'level': 68, 'icon': 'droplet'},
            {'name': 'Ram Grease', 'level': 55, 'icon': 'droplet'},
            {'name': 'Die Lubricant', 'level': 72, 'icon': 'droplet'},
            {'name': 'Hydraulic Pressure', 'level': 89, 'icon': 'gauge'},
        ],
    },
    'MCH-WJ-04': {
        'purchaseDate': '2022-03-20', 'depreciationYears': 10, 'wearLevel': 42, 'totalHours': 8900,
        'partsChanged': ['Torch nozzle (2026)', 'Contact tip set (2026)', 'Wire feeder motor (2025)'],
        'maintenanceLog': [
            {'date': '2026-03-10', 'type': 'Corrective', 'desc': 'Torch nozzle & contact tip replacement', 'cost': 3200},
            {'date': '2025-12-05', 'type': 'Preventive', 'desc': 'Wire feeder calibration & gas flow test', 'cost': 2100},
            {'date': '2025-07-20', 'type': 'Corrective', 'desc': 'Arc stabilizer board replacement', 'cost': 9500},
        ],
        'resources': [
            {'name': 'Shielding Gas (Argon)', 'level': 57, 'icon': 'gauge'},
            {'name': 'Welding Wire Spool', 'level': 33, 'icon': 'gauge'},
            {'name': 'Coolant (Torch)', 'level': 79, 'icon': 'thermometer'},
            {'name': 'Contact Tip Wear', 'level': 41, 'icon': 'droplet'},
        ],
    },
    'MCH-QC-05': {
        'purchaseDate': '2023-01-12', 'depreciationYears': 12, 'wearLevel': 12, 'totalHours': 6200,
        'partsChanged': ['Spray nozzle assembly (2026)', 'QC camera lens (2025)'],
        'maintenanceLog': [
            {'date': '2026-03-01', 'type': 'Preventive', 'desc': 'Spray nozzle cleaning & QC camera calibration', 'cost': 4500},
            {'date': '2025-10-15', 'type': 'Preventive', 'desc': 'Oven thermocouple replacement', 'cost': 1800},
        ],
        'resources': [
            {'name': 'Coating Solution', 'level': 74, 'icon': 'droplet'},
            {'name': 'Solvent / Cleaner', 'level': 62, 'icon': 'droplet'},
            {'name': 'Oven Gas Supply', 'level': 85, 'icon': 'thermometer'},
            {'name': 'Camera Calibration', 'level': 96, 'icon': 'gauge'},
        ],
    },
}

MACHINE_PIPELINE_DEFAULTS = {
    'MCH-UL-01': {
        'visual_type': 'uncoiler',
        'description': 'Uncoils and levels metal sheet stock',
        'metrics': [
            {'key': 'feedrate', 'label': 'Feed Rate', 'unit': 'm/min', 'idle': 0, 'range': [12, 18], 'jitter': 0.5},
            {'key': 'tension', 'label': 'Tension', 'unit': 'kN', 'idle': 0, 'range': [8, 15], 'jitter': 0.3},
            {'key': 'temp', 'label': 'Temperature', 'unit': '\u00b0C', 'idle': 22, 'range': [35, 55], 'jitter': 1.0},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.5, 'range': [15, 28], 'jitter': 0.8},
            {'key': 'rpm', 'label': 'RPM', 'unit': 'rpm', 'idle': 0, 'range': [120, 300], 'jitter': 5},
        ],
        'defect_types': ['Coil edge crack', 'Uneven tension distribution', 'Surface delamination', 'Thickness deviation OOT'],
        'defect_causes': ['Raw material inconsistency', 'Tension calibration drift', 'Roller surface wear', 'Coil edge damage during transit'],
        'scrap_rate': {'min': 0.5, 'max': 1.5, 'type': 'Edge trim'},
    },
    'MCH-SC-02': {
        'visual_type': 'shearing',
        'description': 'Precision shearing and cutting operations',
        'metrics': [
            {'key': 'cutlen', 'label': 'Cut Length', 'unit': 'mm', 'idle': 0, 'range': [500, 3000], 'jitter': 2},
            {'key': 'bladerpm', 'label': 'Blade RPM', 'unit': 'rpm', 'idle': 0, 'range': [800, 1500], 'jitter': 10},
            {'key': 'cutspeed', 'label': 'Cut Speed', 'unit': 'm/min', 'idle': 0, 'range': [15, 40], 'jitter': 0.5},
            {'key': 'scrap', 'label': 'Scrap Rate', 'unit': '%', 'idle': 0, 'range': [1.5, 4.0], 'jitter': 0.2},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.3, 'range': [22, 45], 'jitter': 1.2},
        ],
        'defect_types': ['Dimensional deviation >0.5mm', 'Burr formation', 'Blade misalignment', 'Shear angle error'],
        'defect_causes': ['Blade dulling beyond tolerance', 'Hydraulic pressure fluctuation', 'Guide rail misalignment', 'Material hardness variance'],
        'scrap_rate': {'min': 1.5, 'max': 4.0, 'type': 'Cut-off waste'},
    },
    'MCH-PB-03': {
        'visual_type': 'press_brake',
        'description': 'Hydraulic press brake bending',
        'metrics': [
            {'key': 'angle', 'label': 'Bend Angle', 'unit': '\u00b0', 'idle': 0, 'range': [15, 135], 'jitter': 0.3},
            {'key': 'tonnage', 'label': 'Tonnage', 'unit': 'ton', 'idle': 0, 'range': [40, 200], 'jitter': 2},
            {'key': 'strokes', 'label': 'Stroke Rate', 'unit': '/min', 'idle': 0, 'range': [8, 20], 'jitter': 1},
            {'key': 'pressure', 'label': 'Pressure', 'unit': 'MPa', 'idle': 0, 'range': [12, 35], 'jitter': 0.5},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.4, 'range': [30, 75], 'jitter': 1.5},
        ],
        'defect_types': ['Spring-back error >2\u00b0', 'Angle deviation', 'Die mark impression', 'Micro-fracture at bend'],
        'defect_causes': ['Die wear beyond spec', 'Tonnage miscalculation', 'Material spring-back coefficient error', 'Backgauge positioning drift'],
        'scrap_rate': {'min': 0.3, 'max': 1.2, 'type': 'Bend trim'},
    },
    'MCH-WJ-04': {
        'visual_type': 'welding',
        'description': 'MIG/TIG welding and joining',
        'metrics': [
            {'key': 'arctemp', 'label': 'Arc Temp', 'unit': '\u00b0C', 'idle': 22, 'range': [3000, 5500], 'jitter': 100},
            {'key': 'wirefeed', 'label': 'Wire Feed', 'unit': 'm/min', 'idle': 0, 'range': [5, 15], 'jitter': 0.3},
            {'key': 'current', 'label': 'Weld Current', 'unit': 'A', 'idle': 0, 'range': [120, 350], 'jitter': 5},
            {'key': 'voltage', 'label': 'Voltage', 'unit': 'V', 'idle': 0, 'range': [18, 32], 'jitter': 0.5},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.2, 'range': [18, 55], 'jitter': 2},
        ],
        'defect_types': ['Weld porosity', 'Incomplete fusion', 'Spatter contamination', 'Undercut defect'],
        'defect_causes': ['Shielding gas flow insufficient', 'Wire feed jam', 'Arc instability \u2014 voltage drop', 'Joint fit-up gap exceeded'],
        'scrap_rate': {'min': 0.8, 'max': 2.5, 'type': 'Weld spatter'},
    },
    'MCH-QC-05': {
        'visual_type': 'qc_inspection',
        'description': 'Surface treatment and quality control',
        'metrics': [
            {'key': 'coating', 'label': 'Coating', 'unit': '\u00b5m', 'idle': 0, 'range': [15, 80], 'jitter': 1},
            {'key': 'curetemp', 'label': 'Cure Temp', 'unit': '\u00b0C', 'idle': 22, 'range': [160, 220], 'jitter': 3},
            {'key': 'defect', 'label': 'Defect Rate', 'unit': '%', 'idle': 0, 'range': [0.5, 3.0], 'jitter': 0.1},
            {'key': 'linespeed', 'label': 'Line Speed', 'unit': 'm/min', 'idle': 0, 'range': [8, 20], 'jitter': 0.3},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.3, 'range': [12, 30], 'jitter': 0.8},
        ],
        'defect_types': ['Coating adhesion failure', 'Surface roughness OOT', 'Pinhole defect', 'Color mismatch'],
        'defect_causes': ['Spray nozzle partial clog', 'Cure oven temperature variance', 'Contaminated substrate', 'Humidity exceeded threshold'],
        'scrap_rate': {'min': 0.2, 'max': 0.8, 'type': 'Coating strip'},
    },
}

DEFAULT_PIPELINE_CONFIG = {
    'visual_type': 'generic',
    'description': 'Custom machine',
    'metrics': [
        {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.3, 'range': [10, 40], 'jitter': 1.0},
        {'key': 'throughput', 'label': 'Throughput', 'unit': 'pcs/hr', 'idle': 0, 'range': [20, 60], 'jitter': 2},
        {'key': 'temp', 'label': 'Temperature', 'unit': '\u00b0C', 'idle': 22, 'range': [30, 70], 'jitter': 1.5},
    ],
    'defect_types': ['General defect', 'Dimensional error', 'Surface anomaly'],
    'defect_causes': ['Calibration drift', 'Material variance', 'Wear accumulation'],
    'scrap_rate': {'min': 0.5, 'max': 2.0, 'type': 'General waste'},
}

# =============================================
# Random data pools for new machines
# =============================================
RANDOM_PARTS_POOL = [
    'Hydraulic Cylinder Seal', 'Laser Lens Assembly', 'Press Brake Die Set',
    'Shear Blade Kit', 'Ball Screw Assembly', 'Servo Motor Unit',
    'Coolant Pump', 'Spindle Bearing', 'Linear Guide Rail',
    'Pneumatic Clamp Cylinder', 'CNC Controller Board', 'Turret Punch Insert',
    'Plasma Torch Nozzle', 'Roller Conveyor Belt', 'Safety Light Curtain',
]

RANDOM_MAINTENANCE_POOL = [
    {'type': 'Preventive', 'desc': 'Scheduled lubrication and alignment check', 'cost_range': [200, 800]},
    {'type': 'Corrective', 'desc': 'Replaced worn hydraulic hoses', 'cost_range': [500, 1500]},
    {'type': 'Preventive', 'desc': 'Calibration of laser optics and sensors', 'cost_range': [300, 1200]},
    {'type': 'Corrective', 'desc': 'Repaired servo drive fault', 'cost_range': [800, 2500]},
    {'type': 'Preventive', 'desc': 'Coolant system flush and filter replacement', 'cost_range': [150, 600]},
    {'type': 'Corrective', 'desc': 'Fixed pneumatic pressure leak in clamping system', 'cost_range': [400, 1000]},
    {'type': 'Preventive', 'desc': 'Inspection of electrical connections and grounding', 'cost_range': [100, 400]},
    {'type': 'Corrective', 'desc': 'Replaced damaged ball screw assembly', 'cost_range': [1200, 3500]},
    {'type': 'Preventive', 'desc': 'Belt tension adjustment and wear inspection', 'cost_range': [100, 350]},
    {'type': 'Corrective', 'desc': 'Rebuilt turret indexing mechanism', 'cost_range': [900, 2800]},
]

RANDOM_RESOURCES_POOL = [
    {'name': 'Hydraulic Oil', 'icon': 'droplet'},
    {'name': 'Coolant', 'icon': 'thermometer'},
    {'name': 'Lubricant', 'icon': 'droplet'},
    {'name': 'Compressed Air', 'icon': 'gauge'},
    {'name': 'Shielding Gas', 'icon': 'gauge'},
    {'name': 'Abrasive Media', 'icon': 'gauge'},
    {'name': 'Grease', 'icon': 'droplet'},
    {'name': 'Cutting Fluid', 'icon': 'thermometer'},
]

RANDOM_PIPELINE_CONFIGS = [
    {
        'visual_type': 'laser_cutter',
        'description': 'Fiber laser cutting system',
        'metrics': [
            {'key': 'power', 'label': 'Laser Power', 'unit': 'kW', 'idle': 0.2, 'range': [2, 6], 'jitter': 0.3},
            {'key': 'feedrate', 'label': 'Cut Speed', 'unit': 'm/min', 'idle': 0, 'range': [8, 25], 'jitter': 1.0},
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C', 'idle': 22, 'range': [30, 50], 'jitter': 1.0},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.5, 'range': [12, 35], 'jitter': 0.8},
            {'key': 'gas_pressure', 'label': 'Assist Gas', 'unit': 'bar', 'idle': 0, 'range': [8, 18], 'jitter': 0.5},
        ],
        'defect_types': ['Dross formation', 'Kerf deviation', 'Heat-affected zone discoloration', 'Incomplete cut'],
        'defect_causes': ['Nozzle contamination', 'Focus drift', 'Gas pressure fluctuation', 'Material reflectivity'],
        'scrap_rate': {'min': 0.3, 'max': 1.2, 'type': 'Cut-off waste'},
    },
    {
        'visual_type': 'cnc_punch',
        'description': 'CNC turret punch press',
        'metrics': [
            {'key': 'hits', 'label': 'Hit Rate', 'unit': 'hits/min', 'idle': 0, 'range': [180, 400], 'jitter': 10},
            {'key': 'tonnage', 'label': 'Tonnage', 'unit': 'ton', 'idle': 0, 'range': [10, 30], 'jitter': 1.0},
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C', 'idle': 22, 'range': [28, 45], 'jitter': 0.8},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.4, 'range': [15, 45], 'jitter': 1.5},
        ],
        'defect_types': ['Burr formation', 'Slug pull', 'Sheet marking', 'Nibble line irregularity'],
        'defect_causes': ['Tool wear', 'Misalignment', 'Incorrect clearance', 'Sheet thickness variation'],
        'scrap_rate': {'min': 1.0, 'max': 3.0, 'type': 'Slug and skeleton'},
    },
    {
        'visual_type': 'roll_former',
        'description': 'Roll forming line',
        'metrics': [
            {'key': 'linespeed', 'label': 'Line Speed', 'unit': 'm/min', 'idle': 0, 'range': [15, 50], 'jitter': 2.0},
            {'key': 'tension', 'label': 'Strip Tension', 'unit': 'kN', 'idle': 0, 'range': [5, 20], 'jitter': 0.5},
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C', 'idle': 22, 'range': [30, 55], 'jitter': 1.0},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.3, 'range': [10, 30], 'jitter': 1.0},
        ],
        'defect_types': ['Profile twist', 'Bow and camber', 'Flare', 'Edge wave'],
        'defect_causes': ['Roll wear', 'Strip width variation', 'Incorrect roll gap', 'Lubrication failure'],
        'scrap_rate': {'min': 0.5, 'max': 2.0, 'type': 'End trim'},
    },
    {
        'visual_type': 'plasma_cutter',
        'description': 'CNC plasma cutting table',
        'metrics': [
            {'key': 'current', 'label': 'Arc Current', 'unit': 'A', 'idle': 0, 'range': [40, 200], 'jitter': 5},
            {'key': 'feedrate', 'label': 'Cut Speed', 'unit': 'm/min', 'idle': 0, 'range': [3, 12], 'jitter': 0.5},
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C', 'idle': 22, 'range': [35, 65], 'jitter': 1.5},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.3, 'range': [20, 60], 'jitter': 2.0},
        ],
        'defect_types': ['Dross adhesion', 'Bevel angle error', 'Top edge rounding', 'Arc gouging'],
        'defect_causes': ['Consumable wear', 'Torch height drift', 'Gas flow error', 'Pierce delay'],
        'scrap_rate': {'min': 1.0, 'max': 3.5, 'type': 'Kerf and skeleton'},
    },
    {
        'visual_type': 'deburring',
        'description': 'Deburring and edge finishing machine',
        'metrics': [
            {'key': 'belt_speed', 'label': 'Belt Speed', 'unit': 'm/s', 'idle': 0, 'range': [8, 20], 'jitter': 0.5},
            {'key': 'throughput', 'label': 'Throughput', 'unit': 'pcs/hr', 'idle': 0, 'range': [30, 80], 'jitter': 3},
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C', 'idle': 22, 'range': [25, 40], 'jitter': 0.5},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.2, 'range': [5, 18], 'jitter': 0.8},
        ],
        'defect_types': ['Incomplete deburring', 'Over-rounding', 'Surface scratch', 'Grain direction mark'],
        'defect_causes': ['Abrasive wear', 'Belt tracking error', 'Feed rate mismatch', 'Incorrect grit selection'],
        'scrap_rate': {'min': 0.2, 'max': 1.0, 'type': 'Abrasive waste'},
    },
    {
        'visual_type': 'stamping_press',
        'description': 'Hydraulic stamping press',
        'metrics': [
            {'key': 'force', 'label': 'Press Force', 'unit': 'ton', 'idle': 0, 'range': [50, 250], 'jitter': 5},
            {'key': 'spm', 'label': 'Strokes/Min', 'unit': 'spm', 'idle': 0, 'range': [15, 60], 'jitter': 2},
            {'key': 'temp', 'label': 'Temperature', 'unit': '°C', 'idle': 22, 'range': [30, 55], 'jitter': 1.0},
            {'key': 'energy', 'label': 'Energy', 'unit': 'kW', 'idle': 0.5, 'range': [25, 80], 'jitter': 3.0},
        ],
        'defect_types': ['Wrinkling', 'Tearing', 'Springback', 'Die mark'],
        'defect_causes': ['Die wear', 'Blank misalignment', 'Insufficient blank holder force', 'Material thickness variation'],
        'scrap_rate': {'min': 0.8, 'max': 2.5, 'type': 'Trim and scrap'},
    },
]


def _generate_random_machine_detail(machine_name):
    """Generate randomized, realistic sheet metal machine detail data."""
    now = timezone.now()
    # Random purchase date 1-5 years ago
    days_ago = random.randint(365, 365 * 5)
    purchase_date = (now - datetime.timedelta(days=days_ago)).date()

    # Random parts changed
    num_parts = random.randint(0, 3)
    parts = random.sample(RANDOM_PARTS_POOL, min(num_parts, len(RANDOM_PARTS_POOL)))
    parts_changed = [
        '{} ({})'.format(p, random.randint(purchase_date.year, now.year))
        for p in parts
    ]

    # Random maintenance log
    num_logs = random.randint(1, 3)
    maint_templates = random.sample(RANDOM_MAINTENANCE_POOL, min(num_logs, len(RANDOM_MAINTENANCE_POOL)))
    maintenance_log = []
    for tmpl in maint_templates:
        log_days_ago = random.randint(30, days_ago)
        log_date = (now - datetime.timedelta(days=log_days_ago)).strftime('%Y-%m-%d')
        cost = random.randint(tmpl['cost_range'][0], tmpl['cost_range'][1])
        maintenance_log.append({
            'date': log_date,
            'type': tmpl['type'],
            'desc': tmpl['desc'],
            'cost': cost,
        })

    # Random resources
    num_resources = random.randint(3, 5)
    resource_templates = random.sample(RANDOM_RESOURCES_POOL, min(num_resources, len(RANDOM_RESOURCES_POOL)))
    resources = [
        {'name': r['name'], 'level': random.randint(30, 100), 'icon': r['icon']}
        for r in resource_templates
    ]

    # Random pipeline config
    pipeline_config = dict(random.choice(RANDOM_PIPELINE_CONFIGS))
    pipeline_config['description'] = machine_name

    return {
        'purchaseDate': str(purchase_date),
        'depreciationYears': random.randint(8, 20),
        'wearLevel': random.randint(5, 60),
        'totalHours': random.randint(500, 15000),
        'partsChanged': parts_changed,
        'maintenanceLog': maintenance_log,
        'resources': resources,
        'pipeline_config': pipeline_config,
    }




def _compute_health(usage, threshold):
    """Weibull-inspired failure probability and health score."""
    ratio = usage / max(threshold, 1)
    failure_prob = 1 - math.exp(-(ratio ** 2.5))
    health = max(0, 100 - failure_prob * 100)
    if health >= 80:
        status = 'Operational'
    elif health >= 60:
        status = 'Wear Detected'
    elif health >= 40:
        status = 'Maintenance Recommended'
    else:
        status = 'Critical \u2014 Replace Components'
    return {
        'failure_prob': round(failure_prob * 100, 1),
        'health': round(health, 1),
        'status': status,
    }


def _ensure_machine_records():
    """Create MachineHealth records if they don't exist. Seed detail_data and pipeline_config from defaults."""
    for md in MACHINE_DEFAULTS:
        defaults = {
            'machine_name': md['machine_name'],
            'failure_threshold': md['failure_threshold'],
            'position': md.get('position', 0),
        }
        detail = MACHINE_DETAIL_DEFAULTS.get(md['machine_id'], {})
        pipeline = MACHINE_PIPELINE_DEFAULTS.get(md['machine_id'], {})
        if detail:
            merged = dict(detail)
            if pipeline:
                merged['pipeline_config'] = pipeline
            defaults['detail_data'] = merged
        obj, created = MachineHealth.objects.get_or_create(
            machine_id=md['machine_id'],
            defaults=defaults,
        )
        if not created:
            update_fields = []
            # Seed detail_data for existing records that have none
            if not obj.detail_data and detail:
                obj.detail_data = detail
                update_fields.append('detail_data')
            # Seed pipeline_config if missing
            if obj.detail_data and 'pipeline_config' not in obj.detail_data and pipeline:
                obj.detail_data['pipeline_config'] = pipeline
                update_fields.append('detail_data')
            if update_fields:
                obj.save(update_fields=list(set(update_fields)))


def health(request):
    _ensure_machine_records()
    machines = MachineHealth.objects.all().order_by('position')
    machine_data = []
    for m in machines:
        h = _compute_health(m.usage_count, m.failure_threshold)
        machine_data.append({
            'machine_id': m.machine_id,
            'machine_name': m.machine_name,
            'usage_count': m.usage_count,
            'failure_threshold': m.failure_threshold,
            'position': m.position,
            'detail_data': m.detail_data or MACHINE_DETAIL_DEFAULTS.get(m.machine_id, {}),
            **h,
        })
    context = {
        'active_tab': 'health',
        'machines_json': json.dumps(machine_data),
    }
    return render(request, 'dashboard/health.html', context)


def machine_health_data(request):
    _ensure_machine_records()
    machines = MachineHealth.objects.all().order_by('position')
    data = []
    for m in machines:
        h = _compute_health(m.usage_count, m.failure_threshold)
        data.append({
            'machine_id': m.machine_id,
            'machine_name': m.machine_name,
            'usage_count': m.usage_count,
            'failure_threshold': m.failure_threshold,
            'position': m.position,
            'detail_data': m.detail_data or MACHINE_DETAIL_DEFAULTS.get(m.machine_id, {}),
            **h,
        })
    return JsonResponse({'machines': data})


@require_POST
def update_failure_threshold(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = data.get('machine_id')
    threshold = data.get('threshold')
    if not machine_id or threshold is None:
        return JsonResponse({'error': 'machine_id and threshold required'}, status=400)
    try:
        m = MachineHealth.objects.get(machine_id=machine_id)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': 'Machine not found'}, status=404)
    m.failure_threshold = int(threshold)
    m.save()
    log_event('threshold', 'info', f'Threshold updated: {m.machine_name}',
              f'New threshold: {m.failure_threshold}', machine=m)
    h = _compute_health(m.usage_count, m.failure_threshold)
    return JsonResponse({'success': True, **h})


@require_POST
def reset_machine(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = data.get('machine_id')
    if not machine_id:
        return JsonResponse({'error': 'machine_id required'}, status=400)
    try:
        m = MachineHealth.objects.get(machine_id=machine_id)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': 'Machine not found'}, status=404)
    m.usage_count = 0
    m.last_maintenance = timezone.now()
    m.save()
    log_event('machine', 'info', f'Machine reset: {m.machine_name} ({machine_id})',
              'Usage counter reset to 0, maintenance timestamp updated', machine=m)
    h = _compute_health(0, m.failure_threshold)
    return JsonResponse({'success': True, **h})


@require_POST
def increment_machine_usage(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = data.get('machine_id')
    if not machine_id:
        return JsonResponse({'error': 'machine_id required'}, status=400)
    _ensure_machine_records()
    MachineHealth.objects.filter(machine_id=machine_id).update(
        usage_count=models.F('usage_count') + 1
    )
    # Return updated health data so manufacturing page can enforce failures
    m = MachineHealth.objects.get(machine_id=machine_id)
    if m.usage_count >= m.failure_threshold:
        log_event('machine', 'critical', f'Machine at failure threshold: {m.machine_name}',
                  f'Usage {m.usage_count}/{m.failure_threshold}', machine=m)
    elif m.usage_count >= int(m.failure_threshold * 0.8):
        log_event('machine', 'warning', f'Machine wear high: {m.machine_name}',
                  f'Usage {m.usage_count}/{m.failure_threshold}', machine=m)
    h = _compute_health(m.usage_count, m.failure_threshold)
    return JsonResponse({
        'success': True,
        'machine_id': machine_id,
        'usage_count': m.usage_count,
        'failure_threshold': m.failure_threshold,
        **h,
    })


@require_POST
def update_machine_detail(request):
    """Update machine detail_data (resources, parts, maintenance log, equipment info)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = data.get('machine_id')
    detail_data = data.get('detail_data')
    if not machine_id or detail_data is None:
        return JsonResponse({'error': 'machine_id and detail_data required'}, status=400)
    try:
        m = MachineHealth.objects.get(machine_id=machine_id)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': 'Machine not found'}, status=404)
    m.detail_data = detail_data
    m.save(update_fields=['detail_data'])
    return JsonResponse({'success': True, 'machine_id': machine_id})


@require_POST
def add_machine(request):
    """Add a new machine to the pipeline."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_name = data.get('machine_name', '').strip()
    machine_id = data.get('machine_id', '').strip()
    if not machine_name:
        return JsonResponse({'error': 'machine_name required'}, status=400)
    if not machine_id:
        # Auto-generate ID
        count = MachineHealth.objects.count()
        machine_id = f'MCH-CU-{count + 1:02d}'
    if MachineHealth.objects.filter(machine_id=machine_id).exists():
        return JsonResponse({'error': 'machine_id already exists'}, status=400)
    position = MachineHealth.objects.count()
    detail = _generate_random_machine_detail(machine_name)
    m = MachineHealth.objects.create(
        machine_id=machine_id,
        machine_name=machine_name,
        failure_threshold=data.get('failure_threshold', 10),
        position=position,
        detail_data=detail,
    )
    log_event('machine', 'info', f'Machine added: {m.machine_name} ({m.machine_id})',
              f'Threshold: {m.failure_threshold}', machine=m)
    h = _compute_health(m.usage_count, m.failure_threshold)
    return JsonResponse({
        'success': True,
        'machine': {
            'machine_id': m.machine_id,
            'machine_name': m.machine_name,
            'usage_count': m.usage_count,
            'failure_threshold': m.failure_threshold,
            'position': m.position,
            'detail_data': m.detail_data,
            **h,
        },
    })


@require_POST
def delete_machine(request):
    """Delete a machine and re-number positions."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = data.get('machine_id')
    if not machine_id:
        return JsonResponse({'error': 'machine_id required'}, status=400)
    try:
        m = MachineHealth.objects.get(machine_id=machine_id)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': 'Machine not found'}, status=404)
    machine_name = m.machine_name
    m.delete()
    log_event('machine', 'warning', f'Machine deleted: {machine_name} ({machine_id})', '')
    # Re-number positions
    for i, obj in enumerate(MachineHealth.objects.order_by('position')):
        if obj.position != i:
            obj.position = i
            obj.save(update_fields=['position'])
    return JsonResponse({'success': True})


@require_POST
def reorder_machines(request):
    """Swap a machine with its neighbor (up or down)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = data.get('machine_id')
    direction = data.get('direction')  # 'up' or 'down'
    if not machine_id or direction not in ('up', 'down'):
        return JsonResponse({'error': 'machine_id and direction (up/down) required'}, status=400)
    try:
        m = MachineHealth.objects.get(machine_id=machine_id)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': 'Machine not found'}, status=404)
    target_pos = m.position - 1 if direction == 'up' else m.position + 1
    try:
        neighbor = MachineHealth.objects.get(position=target_pos)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': 'Cannot move further'}, status=400)
    # Swap positions
    m.position, neighbor.position = neighbor.position, m.position
    m.save(update_fields=['position'])
    neighbor.save(update_fields=['position'])
    return JsonResponse({'success': True})


def logs(request):
    """Global logs page with filtering."""
    qs = GlobalLog.objects.all()

    event_type = request.GET.get('event_type', '')
    severity = request.GET.get('severity', '')
    search = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    order_id = request.GET.get('order', '')
    around = request.GET.get('around', '')

    if event_type:
        qs = qs.filter(event_type=event_type)
    if severity:
        qs = qs.filter(severity=severity)
    if search:
        qs = qs.filter(
            models.Q(title__icontains=search) | models.Q(description__icontains=search)
        )
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)
    # When order_id is provided via chart click-through, do NOT filter —
    # show all logs so the user sees context before/after. We'll mark which
    # log entry to scroll to via highlight_log_id.
    highlight_log_id = None
    if not order_id:
        if around:
            try:
                center = datetime.datetime.fromisoformat(around)
                qs = qs.filter(
                    timestamp__gte=center - datetime.timedelta(hours=2),
                    timestamp__lte=center + datetime.timedelta(hours=2),
                )
            except (ValueError, TypeError):
                pass

    logs_list = qs.select_related(
        'delivery', 'manufacturing_order', 'machine', 'scrap_event'
    )[:500]

    # Find the first log entry that matches the target order so we can scroll to it
    if order_id:
        for log in logs_list:
            if (log.manufacturing_order and log.manufacturing_order.order_id == order_id) or \
               order_id in log.title:
                highlight_log_id = log.id
                break

    context = {
        'active_tab': 'logs',
        'logs': logs_list,
        'event_types': GlobalLog.EVENT_TYPE_CHOICES,
        'severities': GlobalLog.SEVERITY_CHOICES,
        'filter_event_type': event_type,
        'filter_severity': severity,
        'filter_search': search,
        'filter_date_from': date_from,
        'filter_date_to': date_to,
        'filter_order': order_id,
        'highlight_log_id': highlight_log_id,
    }
    return render(request, 'dashboard/logs.html', context)


def materials(request):
    warehouse, wh_ctx = _warehouse_context(request)
    mats = Material.objects.all().order_by('id')
    materials_list = []
    for m in mats:
        d_qs = m.delivery_set.all()
        if warehouse:
            d_qs = d_qs.filter(warehouse=warehouse)
        total_qty = 0
        for d in d_qs:
            try:
                total_qty += int(''.join(c for c in d.quantity if c.isdigit()))
            except (ValueError, IndexError):
                pass
        loc_qs = Delivery.objects.filter(material=m, status__in=['pending', 'stored'])
        if warehouse:
            loc_qs = loc_qs.filter(warehouse=warehouse)
        shelf_ids = list(loc_qs.values_list('shelf_id', flat=True))
        sector_units = set()
        for sid in shelf_ids:
            p = sid.split('-')
            if len(p) == 3:
                sector_units.add(f'{p[0]}-{p[1]}')
        delivery_count = d_qs.count()
        # Only show materials that have data in this warehouse
        if delivery_count == 0 and total_qty == 0:
            continue
        materials_list.append({
            'id': m.id,
            'name': m.name,
            'category': m.category,
            'delivery_count': delivery_count,
            'total_quantity': str(total_qty) if total_qty > 0 else '\u2014',
            'sector_units': sorted(sector_units),
            'locations': sorted(set(shelf_ids)),
        })
    context = {
        'active_tab': 'materials',
        'materials': materials_list,
        **wh_ctx,
    }
    return render(request, 'dashboard/materials.html', context)


# =============================================
# Warehouse Selection API
# =============================================

@require_POST
def set_warehouse(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    warehouse_id = data.get('warehouse_id')
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
        request.session['current_warehouse_id'] = wh.id
        return JsonResponse({'success': True, 'warehouse_id': wh.id, 'name': wh.name, 'num_docks': wh.num_docks})
    except Warehouse.DoesNotExist:
        return JsonResponse({'error': 'Warehouse not found'}, status=404)


@require_GET
def warehouse_list(request):
    warehouses = list(Warehouse.objects.values('id', 'name', 'code', 'num_docks'))
    current = _get_current_warehouse(request)
    return JsonResponse({'warehouses': warehouses, 'current_id': current.id if current else None})


# =============================================
# Settings Page
# =============================================

def settings_page(request):
    ai = AISettings.get()
    context = {
        'active_tab': 'settings',
        'ai_settings': ai,
        'has_credentials': bool(ai.gcp_project_id and ai.service_account_json),
    }
    return render(request, 'dashboard/settings.html', context)


from django.views.decorators.csrf import csrf_exempt as _csrf_exempt

@_csrf_exempt
@require_POST
def save_ai_settings(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ai = AISettings.get()
    ai.gcp_project_id = body.get('gcp_project_id', '').strip()

    svc_json = body.get('service_account_json', '').strip()
    if svc_json:
        try:
            parsed = json.loads(svc_json)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON in service account key'}, status=400)
        ai.service_account_json = svc_json
        # Auto-fill project_id from JSON if user left it empty
        if not ai.gcp_project_id and parsed.get('project_id'):
            ai.gcp_project_id = parsed['project_id']

    ai.save()
    return JsonResponse({'ok': True})


# =============================================
# Profile Selection & Operator Views
# =============================================

def profile_select(request):
    role = request.session.get('selected_role')
    if role == 'warehouse_operator':
        return redirect('dashboard:operator_home')
    elif role == 'maintenance_tech':
        return redirect('dashboard:maintenance_home')
    elif role == 'production_supervisor':
        return redirect('dashboard:production_home')
    return render(request, 'dashboard/profile_select.html')


@require_POST
def set_profile(request):
    role = request.POST.get('role', '')
    if role in ('warehouse_operator', 'maintenance_tech', 'production_supervisor'):
        request.session['selected_role'] = role
        if role == 'warehouse_operator':
            return redirect('dashboard:operator_home')
        elif role == 'maintenance_tech':
            return redirect('dashboard:maintenance_home')
        elif role == 'production_supervisor':
            return redirect('dashboard:production_home')
    return redirect('dashboard:profile_select')


def clear_profile(request):
    request.session.pop('selected_role', None)
    return redirect('dashboard:profile_select')


def _require_operator(request):
    if request.session.get('selected_role') != 'warehouse_operator':
        return redirect('dashboard:profile_select')
    return None


def operator_home(request):
    redir = _require_operator(request)
    if redir:
        return redir
    warehouse = _get_current_warehouse(request)
    return render(request, 'dashboard/operator/home.html', {
        'active_tab': 'home',
        'role': 'warehouse_operator',
        'current_warehouse': warehouse,
    })


def operator_dashboard(request):
    redir = _require_operator(request)
    if redir:
        return redir
    warehouse, wh_ctx = _warehouse_context(request)
    today = date.today()
    pending = Delivery.objects.filter(status='pending')
    stored_today = Delivery.objects.filter(status='stored')
    arriving = Delivery.objects.filter(date=today)
    if warehouse:
        pending = pending.filter(warehouse=warehouse)
        stored_today = stored_today.filter(warehouse=warehouse)
        arriving = arriving.filter(warehouse=warehouse)

    recent_logs = GlobalLog.objects.filter(
        event_type__in=['delivery', 'warehouse', 'shipment']
    ).order_by('-timestamp')[:5]

    context = {
        'active_tab': 'dashboard',
        'active_sub': 'dashboard',
        'role': 'warehouse_operator',
        'mode': 'ui',
        'stats': {
            'pending_deliveries': pending.count(),
            'storage_utilization': _overall_utilization(warehouse),
            'total_materials': Material.objects.count(),
            'arriving_today': arriving.count(),
        },
        'recent_logs': recent_logs,
        **wh_ctx,
    }
    return render(request, 'dashboard/operator/dashboard.html', context)


def operator_delivery(request):
    redir = _require_operator(request)
    if redir:
        return redir
    warehouse, wh_ctx = _warehouse_context(request)
    cfg = _get_warehouse_config(warehouse)
    d_qs = Delivery.objects.select_related('material').exclude(status='deleted')
    if warehouse:
        d_qs = d_qs.filter(warehouse=warehouse)
    delivery_list = []
    for d in d_qs:
        slot_qs = ShelfSlot.objects.filter(delivery=d, is_occupied=True)
        pallets_stored = slot_qs.count()
        try:
            pallets_needed = int(''.join(c for c in d.quantity if c.isdigit()))
        except (ValueError, IndexError):
            pallets_needed = 1
        shelf_occ_qs = ShelfSlot.objects.filter(shelf_id=d.shelf_id, is_occupied=True)
        if warehouse:
            shelf_occ_qs = shelf_occ_qs.filter(warehouse=warehouse)
        shelf_occupied = shelf_occ_qs.count()
        delivery_list.append({
            'id': d.id,
            'manufacturer': d.manufacturer,
            'date': str(d.date),
            'created_at': d.created_at.strftime('%b %d, %I:%M %p') if d.created_at else str(d.date),
            'size': d.size,
            'batch_id': d.batch_id,
            'quantity': d.quantity,
            'shelf_id': d.shelf_id,
            'status': d.status,
            'pallets_stored': pallets_stored,
            'pallets_needed': pallets_needed,
            'shelf_occupied': shelf_occupied,
            'shelf_full': shelf_occupied >= cfg['slots_per_shelf'],
            'material_id': d.material.id if d.material else None,
            'material_name': d.material.name if d.material else '',
        })

    total_slots = len(cfg['sectors']) * len(cfg['units']) * cfg['shelves_per_unit'] * cfg['slots_per_shelf']
    occ_qs = ShelfSlot.objects.filter(is_occupied=True, delivery__isnull=False)
    pend_qs = Delivery.objects.filter(status='pending')
    stor_qs = Delivery.objects.filter(status='stored')
    if warehouse:
        occ_qs = occ_qs.filter(warehouse=warehouse)
        pend_qs = pend_qs.filter(warehouse=warehouse)
        stor_qs = stor_qs.filter(warehouse=warehouse)
    occupied_slots = occ_qs.count()

    context = {
        'active_tab': 'delivery',
        'active_sub': 'delivery',
        'role': 'warehouse_operator',
        'mode': 'ui',
        'slots_per_shelf': cfg['slots_per_shelf'],
        'deliveries': delivery_list,
        'total_slots': total_slots,
        'occupied_slots': occupied_slots,
        'available_slots': total_slots - occupied_slots,
        'pending_count': pend_qs.count(),
        'stored_count': stor_qs.count(),
        **wh_ctx,
    }
    return render(request, 'dashboard/operator/delivery.html', context)


def operator_materials(request):
    redir = _require_operator(request)
    if redir:
        return redir
    warehouse, wh_ctx = _warehouse_context(request)
    mats = Material.objects.all().order_by('id')
    materials_list = []
    for m in mats:
        d_qs = m.delivery_set.all()
        if warehouse:
            d_qs = d_qs.filter(warehouse=warehouse)
        total_qty = 0
        for d in d_qs:
            try:
                total_qty += int(''.join(c for c in d.quantity if c.isdigit()))
            except (ValueError, IndexError):
                pass
        loc_qs = Delivery.objects.filter(material=m, status__in=['pending', 'stored'])
        if warehouse:
            loc_qs = loc_qs.filter(warehouse=warehouse)
        shelf_ids = list(loc_qs.values_list('shelf_id', flat=True))
        sector_units = set()
        for sid in shelf_ids:
            p = sid.split('-')
            if len(p) == 3:
                sector_units.add(f'{p[0]}-{p[1]}')
        delivery_count = d_qs.count()
        if delivery_count == 0 and total_qty == 0:
            continue
        materials_list.append({
            'id': m.id,
            'name': m.name,
            'category': m.category,
            'delivery_count': delivery_count,
            'total_quantity': str(total_qty) if total_qty > 0 else '\u2014',
            'sector_units': sorted(sector_units),
            'locations': sorted(set(shelf_ids)),
        })
    context = {
        'active_tab': 'materials',
        'active_sub': 'materials',
        'role': 'warehouse_operator',
        'mode': 'ui',
        'materials': materials_list,
        **wh_ctx,
    }
    return render(request, 'dashboard/operator/materials.html', context)


def operator_finished_goods(request):
    """Show completed manufacturing orders that need to be stored in warehouses."""
    redir = _require_operator(request)
    if redir:
        return redir

    # Orders ready to be stored (completed + PASS, not yet on a shelf)
    stored_order_ids = ShelfSlot.objects.filter(
        manufacturing_order__isnull=False, is_occupied=True
    ).values_list('manufacturing_order_id', flat=True)

    pending_orders = ManufacturingOrder.objects.filter(
        status='completed', quality='PASS'
    ).exclude(id__in=stored_order_ids).order_by('-created_at')

    # Orders already stored as finished goods
    stored_slots = ShelfSlot.objects.filter(
        manufacturing_order__isnull=False, is_occupied=True
    ).select_related('manufacturing_order', 'warehouse').order_by('-stored_at')

    warehouses = Warehouse.objects.all().order_by('id')

    context = {
        'active_tab': 'finished_goods',
        'active_sub': 'finished_goods',
        'role': 'warehouse_operator',
        'mode': 'ui',
        'pending_orders': pending_orders,
        'stored_slots': stored_slots,
        'warehouses': warehouses,
    }
    return render(request, 'dashboard/operator/finished_goods.html', context)


def operator_warehouse(request):
    redir = _require_operator(request)
    if redir:
        return redir
    warehouse = _get_current_warehouse(request)
    warehouses = Warehouse.objects.all().order_by('id')
    context = {
        'active_tab': 'warehouse',
        'active_sub': 'warehouse',
        'role': 'warehouse_operator',
        'mode': 'ui',
        'warehouses': warehouses,
        'current_warehouse': warehouse,
    }
    return render(request, 'dashboard/operator/warehouse.html', context)


def operator_warehouse_view(request, warehouse_id):
    redir = _require_operator(request)
    if redir:
        return redir
    wh = Warehouse.objects.filter(id=warehouse_id).first()
    if not wh:
        from django.http import Http404
        raise Http404("Warehouse not found")

    cells = WarehouseCell.objects.filter(warehouse=wh).order_by('row', 'col')
    storage_cells = cells.filter(cell_type='storage')

    # Gather unit info with occupancy
    units = {}
    for cell in storage_cells:
        key = f"{cell.sector}-{cell.unit}"
        if key not in units:
            units[key] = {
                'sector': cell.sector,
                'unit': cell.unit,
                'label': cell.label or key,
                'shelves': [],
                'total_slots': 0,
                'occupied_slots': 0,
            }

    # Get shelf slot data per unit
    slots = ShelfSlot.objects.filter(warehouse=wh)
    shelf_map = {}
    for slot in slots:
        parts = slot.shelf_id.split('-')
        if len(parts) >= 3:
            unit_key = f"{parts[0]}-{parts[1]}"
            shelf_num = parts[2]
            if unit_key not in shelf_map:
                shelf_map[unit_key] = {}
            if shelf_num not in shelf_map[unit_key]:
                shelf_map[unit_key][shelf_num] = {'total': 0, 'occupied': 0}
            shelf_map[unit_key][shelf_num]['total'] += 1
            if slot.is_occupied:
                shelf_map[unit_key][shelf_num]['occupied'] += 1

    for unit_key, shelf_data in shelf_map.items():
        if unit_key in units:
            for shelf_num, counts in sorted(shelf_data.items(), key=lambda x: int(x[0])):
                units[unit_key]['shelves'].append({
                    'shelf_id': f"{unit_key}-{shelf_num}",
                    'shelf_num': shelf_num,
                    'total': counts['total'],
                    'occupied': counts['occupied'],
                    'free': counts['total'] - counts['occupied'],
                    'pct': round(counts['occupied'] / counts['total'] * 100) if counts['total'] > 0 else 0,
                })
                units[unit_key]['total_slots'] += counts['total']
                units[unit_key]['occupied_slots'] += counts['occupied']

    # Sort units by sector then unit letter
    unit_list = sorted(units.values(), key=lambda u: (u['sector'] or 0, u['unit'] or ''))

    total_slots = sum(u['total_slots'] for u in unit_list)
    occupied_slots = sum(u['occupied_slots'] for u in unit_list)

    # Build occupancy lookup per unit key
    unit_occupancy = {}
    for unit_key, data in units.items():
        t = data['total_slots']
        o = data['occupied_slots']
        if t == 0:
            status = 'empty'
        elif o >= t:
            status = 'full'
        elif o > 0:
            status = 'partial'
        else:
            status = 'empty'
        unit_occupancy[unit_key] = {'occupied': o, 'total': t, 'status': status}

    # Grid data for map (with occupancy)
    cell_list = []
    for cell in cells:
        c = {
            'row': cell.row,
            'col': cell.col,
            'cell_type': cell.cell_type,
            'label': cell.label,
            'sector': cell.sector,
            'unit': cell.unit,
        }
        if cell.cell_type == 'storage' and cell.sector is not None and cell.unit:
            ukey = f"{cell.sector}-{cell.unit}"
            occ = unit_occupancy.get(ukey, {'occupied': 0, 'total': 0, 'status': 'empty'})
            c['occupied'] = occ['occupied']
            c['total'] = occ['total']
            c['status'] = occ['status']
        cell_list.append(c)

    current_warehouse = _get_current_warehouse(request)

    context = {
        'active_tab': 'warehouse',
        'active_sub': 'warehouse',
        'role': 'warehouse_operator',
        'mode': 'ui',
        'warehouse': wh,
        'current_warehouse': current_warehouse,
        'units': unit_list,
        'total_slots': total_slots,
        'occupied_slots': occupied_slots,
        'free_slots': total_slots - occupied_slots,
        'occupancy_pct': round(occupied_slots / total_slots * 100) if total_slots > 0 else 0,
        'storage_count': storage_cells.count(),
        'cells_json': json.dumps(cell_list),
    }
    return render(request, 'dashboard/operator/warehouse_view.html', context)


# =============================================
# Maintenance Technician Views
# =============================================

def _compute_health_pct(usage, threshold):
    if threshold <= 0:
        return 0.0
    ratio = usage / threshold
    fail_prob = 1 - math.exp(-((ratio) ** 3.5))
    return round(max(0, (1 - fail_prob)) * 100, 1)


def _require_maintenance(request):
    if request.session.get('selected_role') != 'maintenance_tech':
        return redirect('dashboard:profile_select')
    return None


def maintenance_home(request):
    redir = _require_maintenance(request)
    if redir:
        return redir
    return render(request, 'dashboard/maintenance/home.html', {
        'active_tab': 'home',
        'role': 'maintenance_tech',
    })


def maintenance_dashboard(request):
    redir = _require_maintenance(request)
    if redir:
        return redir
    today = date.today()
    machines = MachineHealth.objects.all()
    machines_data = []
    total_health = 0
    needs_attention = 0
    for m in machines:
        h = _compute_health_pct(m.usage_count, m.failure_threshold)
        total_health += h
        if h < 50:
            needs_attention += 1
        machines_data.append({
            'machine_id': m.machine_id,
            'machine_name': m.machine_name,
            'health_pct': h,
        })
    avg_health = round(total_health / max(len(machines_data), 1), 1)
    defected_today = ManufacturingOrder.objects.filter(status='defected', created_at__date=today).count()
    scrap_today = ScrapEvent.objects.filter(created_at__date=today).count()
    recent_logs = GlobalLog.objects.filter(
        event_type__in=['machine', 'scrap', 'threshold', 'manufacturing']
    ).order_by('-timestamp')[:10]
    recent_maintenance = MaintenanceEntry.objects.select_related('machine').all()[:5]
    context = {
        'active_tab': 'dashboard',
        'active_sub': 'dashboard',
        'role': 'maintenance_tech',
        'mode': 'ui',
        'today': today.strftime('%A, %B %-d, %Y'),
        'stats': {
            'needs_attention': needs_attention,
            'avg_health': avg_health,
            'defected_today': defected_today,
            'scrap_today': scrap_today,
        },
        'recent_logs': recent_logs,
        'recent_maintenance': recent_maintenance,
    }
    return render(request, 'dashboard/maintenance/dashboard.html', context)


def maintenance_machines(request):
    redir = _require_maintenance(request)
    if redir:
        return redir
    machines = MachineHealth.objects.all()
    machines_list = []
    for m in machines:
        h = _compute_health_pct(m.usage_count, m.failure_threshold)
        if h > 70:
            status = 'healthy'
        elif h > 40:
            status = 'warning'
        elif h > 20:
            status = 'maintenance'
        else:
            status = 'critical'
        recent_entries = MaintenanceEntry.objects.filter(machine=m).order_by('-date')[:5]
        recent_defects = ManufacturingOrder.objects.filter(
            defect_machine_id=m.machine_id, status='defected'
        ).count()
        recent_scrap = ScrapEvent.objects.filter(machine_id=m.machine_id).count()
        machines_list.append({
            'id': m.id,
            'machine_id': m.machine_id,
            'machine_name': m.machine_name,
            'health_pct': h,
            'usage_count': m.usage_count,
            'failure_threshold': m.failure_threshold,
            'last_maintenance': m.last_maintenance,
            'status': status,
            'detail_data': m.detail_data or {},
            'maintenance_entries': recent_entries,
            'defect_count': recent_defects,
            'scrap_count': recent_scrap,
        })
    context = {
        'active_tab': 'machines',
        'active_sub': 'machines',
        'role': 'maintenance_tech',
        'mode': 'ui',
        'machines': machines_list,
    }
    return render(request, 'dashboard/maintenance/machines.html', context)


def maintenance_log_page(request):
    redir = _require_maintenance(request)
    if redir:
        return redir
    entries = MaintenanceEntry.objects.select_related('machine').all()
    # Apply filters
    machine_id = request.GET.get('machine')
    mtype = request.GET.get('type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if machine_id:
        entries = entries.filter(machine__machine_id=machine_id)
    if mtype:
        entries = entries.filter(maintenance_type=mtype)
    if date_from:
        try:
            entries = entries.filter(date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            entries = entries.filter(date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass
    machines = MachineHealth.objects.all().order_by('machine_name')
    context = {
        'active_tab': 'maintenance_log',
        'active_sub': 'maintenance_log',
        'role': 'maintenance_tech',
        'mode': 'ui',
        'entries': entries[:100],
        'machines': machines,
        'filter_machine': machine_id or '',
        'filter_type': mtype or '',
        'filter_date_from': date_from or '',
        'filter_date_to': date_to or '',
    }
    return render(request, 'dashboard/maintenance/maintenance_log.html', context)


def maintenance_logs(request):
    redir = _require_maintenance(request)
    if redir:
        return redir
    logs = GlobalLog.objects.filter(
        event_type__in=['machine', 'scrap', 'manufacturing', 'threshold']
    )
    event_type = request.GET.get('event_type')
    severity = request.GET.get('severity')
    search = request.GET.get('search')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if event_type:
        logs = logs.filter(event_type=event_type)
    if severity:
        logs = logs.filter(severity=severity)
    if search:
        from django.db.models import Q
        logs = logs.filter(Q(title__icontains=search) | Q(description__icontains=search))
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)
    context = {
        'active_tab': 'logs',
        'active_sub': 'logs',
        'role': 'maintenance_tech',
        'mode': 'ui',
        'logs': logs[:100],
        'filter_event_type': event_type or '',
        'filter_severity': severity or '',
        'filter_search': search or '',
        'filter_date_from': date_from or '',
        'filter_date_to': date_to or '',
    }
    return render(request, 'dashboard/maintenance/logs.html', context)


from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_POST
def api_create_maintenance_entry(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    machine_id = body.get('machine_id', '').strip()
    maintenance_type = body.get('maintenance_type', '').strip()
    description = body.get('description', '').strip()
    entry_date = body.get('date', '')
    parts_replaced = body.get('parts_replaced', '').strip()
    technician_notes = body.get('technician_notes', '').strip()
    next_scheduled = body.get('next_scheduled', '')
    if not machine_id or not maintenance_type or not description:
        return JsonResponse({'error': 'machine_id, maintenance_type, and description are required'}, status=400)
    try:
        machine = MachineHealth.objects.get(machine_id=machine_id)
    except MachineHealth.DoesNotExist:
        return JsonResponse({'error': f'Machine {machine_id} not found'}, status=404)
    if not entry_date:
        entry_date = timezone.localdate()
    entry = MaintenanceEntry.objects.create(
        machine=machine,
        date=entry_date,
        maintenance_type=maintenance_type,
        description=description,
        parts_replaced=parts_replaced,
        technician_notes=technician_notes,
        next_scheduled=next_scheduled or None,
    )
    # Update machine last_maintenance
    machine.last_maintenance = timezone.now()
    machine.save(update_fields=['last_maintenance'])
    # Log event
    log_event(
        'machine', 'info',
        f'Maintenance logged: {maintenance_type} on {machine.machine_name}',
        description=description,
        machine=machine,
    )
    return JsonResponse({
        'ok': True,
        'entry': {
            'id': entry.id,
            'machine_name': machine.machine_name,
            'machine_id': machine.machine_id,
            'date': str(entry.date),
            'maintenance_type': entry.maintenance_type,
            'description': entry.description,
            'parts_replaced': entry.parts_replaced,
            'technician_notes': entry.technician_notes,
            'next_scheduled': str(entry.next_scheduled) if entry.next_scheduled else None,
        },
    })


# =============================================
# Production Supervisor Views
# =============================================

def _require_production(request):
    if request.session.get('selected_role') != 'production_supervisor':
        return redirect('dashboard:profile_select')
    return None


def production_home(request):
    redir = _require_production(request)
    if redir:
        return redir
    return render(request, 'dashboard/production/home.html', {
        'active_tab': 'home',
        'role': 'production_supervisor',
    })


def production_dashboard(request):
    redir = _require_production(request)
    if redir:
        return redir
    today = date.today()

    # Manufacturing stats
    orders_today = ManufacturingOrder.objects.filter(created_at__date=today)
    total_orders_today = orders_today.count()
    completed_today = orders_today.filter(status='completed').count()
    defected_today = orders_today.filter(status='defected').count()
    defect_rate = round((defected_today / total_orders_today * 100), 1) if total_orders_today > 0 else 0
    quality_pass = orders_today.filter(quality='PASS').count()
    quality_fail = orders_today.filter(quality='FAIL').count()

    # Machine stats
    machines = MachineHealth.objects.all()
    total_health = 0
    needs_attention = 0
    for m in machines:
        h = _compute_health_pct(m.usage_count, m.failure_threshold)
        total_health += h
        if h < 50:
            needs_attention += 1
    avg_health = round(total_health / machines.count(), 1) if machines.count() > 0 else 0

    # Scrap & warehouse
    scrap_today = ScrapEvent.objects.filter(created_at__date=today).count()
    pending_deliveries = Delivery.objects.filter(status='pending').count()
    utilization = round(_overall_utilization() or 0, 1)

    # Recent logs (all types)
    recent_logs = GlobalLog.objects.order_by('-timestamp')[:15]

    # 12-hour order timeline for chart
    twelve_hours_ago = timezone.now() - timedelta(hours=12)
    timeline_orders = ManufacturingOrder.objects.filter(
        created_at__gte=twelve_hours_ago
    ).order_by('created_at').values(
        'order_id', 'product', 'status', 'quality',
        'defect_machine', 'defect_type', 'created_at',
    )[:100]
    timeline_data = []
    for o in timeline_orders:
        # Find the related log ID for click-to-navigate
        log = GlobalLog.objects.filter(
            manufacturing_order__order_id=o['order_id']
        ).order_by('-timestamp').values_list('id', flat=True).first()
        timeline_data.append({
            'order_id': o['order_id'],
            'product': o['product'],
            'status': o['status'],
            'quality': o['quality'],
            'defect_machine': o['defect_machine'] or '',
            'defect_type': o['defect_type'] or '',
            'created_at_iso': o['created_at'].isoformat(),
            'log_id': log,
        })

    today_str = today.strftime('%A, %B %d, %Y')
    context = {
        'active_tab': 'dashboard',
        'active_sub': 'dashboard',
        'role': 'production_supervisor',
        'mode': 'ui',
        'today': today_str,
        'stats': {
            'total_orders_today': total_orders_today,
            'completed_today': completed_today,
            'defected_today': defected_today,
            'defect_rate': defect_rate,
            'quality_pass': quality_pass,
            'quality_fail': quality_fail,
            'avg_health': avg_health,
            'needs_attention': needs_attention,
            'scrap_today': scrap_today,
            'pending_deliveries': pending_deliveries,
            'utilization': utilization,
        },
        'recent_logs': recent_logs,
        'timeline_orders_json': json.dumps(timeline_data),
    }
    return render(request, 'dashboard/production/dashboard.html', context)


def production_orders(request):
    redir = _require_production(request)
    if redir:
        return redir

    qs = ManufacturingOrder.objects.select_related(
        'delivery', 'delivery__warehouse', 'delivery__material', 'material',
    ).prefetch_related(
        'scrap_events', 'logs',
    ).order_by('-created_at')

    # Filters
    f_status = request.GET.get('status', '')
    f_quality = request.GET.get('quality', '')
    f_product = request.GET.get('product', '')
    f_date_from = request.GET.get('date_from', '')
    f_date_to = request.GET.get('date_to', '')

    if f_status:
        qs = qs.filter(status=f_status)
    if f_quality:
        qs = qs.filter(quality=f_quality)
    if f_product:
        qs = qs.filter(product__icontains=f_product)
    if f_date_from:
        qs = qs.filter(created_at__date__gte=f_date_from)
    if f_date_to:
        qs = qs.filter(created_at__date__lte=f_date_to)

    orders_qs = qs[:200]

    # Build enriched order list with full history
    orders = []
    for o in orders_qs:
        # Delivery & warehouse origin
        d = o.delivery
        delivery_info = None
        if d:
            # Find shelf slots where this delivery's pallets were stored
            stored_slots = list(ShelfSlot.objects.filter(
                delivery=d, is_occupied=True
            ).values_list('shelf_id', flat=True).distinct())
            delivery_info = {
                'batch_id': d.batch_id,
                'manufacturer': d.manufacturer,
                'date': d.date,
                'quantity': d.quantity,
                'shelf_id': d.shelf_id,
                'status': d.status,
                'warehouse_name': d.warehouse.name if d.warehouse else '—',
                'warehouse_code': d.warehouse.code if d.warehouse else '—',
                'material_name': d.material.name if d.material else d.manufacturer,
                'stored_shelves': stored_slots,
                'stored_at': d.created_at,
            }

        # Related logs (full event timeline for this order)
        order_logs = list(o.logs.order_by('timestamp').values(
            'timestamp', 'event_type', 'severity', 'title', 'description', 'id',
        ))

        # Delivery-related logs (when it was received & stored)
        delivery_logs = []
        if d:
            delivery_logs = list(GlobalLog.objects.filter(
                delivery=d
            ).order_by('timestamp').values(
                'timestamp', 'event_type', 'severity', 'title', 'description', 'id',
            ))

        # Scrap events
        scraps = list(o.scrap_events.order_by('created_at').values(
            'machine_name', 'machine_id', 'scrap_type', 'scrap_rate', 'created_at',
        ))

        # Stage data (machine-by-machine processing)
        stage_data = o.stage_data or []
        stage_timestamps = o.stage_timestamps or []

        orders.append({
            'order': o,
            'delivery_info': delivery_info,
            'order_logs': order_logs,
            'delivery_logs': delivery_logs,
            'scraps': scraps,
            'stage_data': stage_data,
            'stage_timestamps': stage_timestamps,
            'timeline': sorted(delivery_logs + order_logs, key=lambda x: x['timestamp']),
        })

    context = {
        'active_tab': 'orders',
        'active_sub': 'orders',
        'role': 'production_supervisor',
        'mode': 'ui',
        'orders': orders,
        'filter_status': f_status,
        'filter_quality': f_quality,
        'filter_product': f_product,
        'filter_date_from': f_date_from,
        'filter_date_to': f_date_to,
    }
    return render(request, 'dashboard/production/orders.html', context)


def production_machines(request):
    redir = _require_production(request)
    if redir:
        return redir
    _ensure_machine_records()
    machines = MachineHealth.objects.all().order_by('position')
    machines_data = []
    for m in machines:
        h = _compute_health_pct(m.usage_count, m.failure_threshold)
        status = 'healthy' if h > 70 else 'warning' if h > 40 else 'maintenance' if h > 20 else 'critical'
        defect_count = ManufacturingOrder.objects.filter(
            defect_machine=m.machine_name, status='defected'
        ).count()
        scrap_count = ScrapEvent.objects.filter(machine_id=m.machine_id).count()
        maintenance_entries = list(MaintenanceEntry.objects.filter(machine=m).order_by('-date')[:5])
        machines_data.append({
            'id': m.id,
            'machine_id': m.machine_id,
            'machine_name': m.machine_name,
            'health_pct': h,
            'usage_count': m.usage_count,
            'failure_threshold': m.failure_threshold,
            'last_maintenance': m.last_maintenance,
            'status': status,
            'position': m.position,
            'detail_data': m.detail_data or {},
            'maintenance_entries': maintenance_entries,
            'defect_count': defect_count,
            'scrap_count': scrap_count,
        })
    context = {
        'active_tab': 'machines',
        'active_sub': 'machines',
        'role': 'production_supervisor',
        'mode': 'ui',
        'machines': machines_data,
    }
    return render(request, 'dashboard/production/machines.html', context)


def production_warehouses(request):
    redir = _require_production(request)
    if redir:
        return redir
    warehouses = Warehouse.objects.all()
    wh_data = []
    for wh in warehouses:
        util = round(_overall_utilization(warehouse=wh) or 0, 1)
        pending = Delivery.objects.filter(warehouse=wh, status='pending').count()
        stored = Delivery.objects.filter(warehouse=wh, status='stored').count()
        wh_data.append({
            'id': wh.id,
            'name': wh.name,
            'code': wh.code,
            'width_m': wh.width_m,
            'length_m': wh.length_m,
            'height_m': wh.height_m,
            'num_docks': wh.num_docks,
            'layout_configured': wh.layout_configured,
            'utilization': util,
            'pending': pending,
            'stored': stored,
        })
    context = {
        'active_tab': 'warehouses',
        'active_sub': 'warehouses',
        'role': 'production_supervisor',
        'mode': 'ui',
        'warehouses': wh_data,
    }
    return render(request, 'dashboard/production/warehouses.html', context)


def production_logs(request):
    redir = _require_production(request)
    if redir:
        return redir

    qs = GlobalLog.objects.all().order_by('-timestamp')

    f_event_type = request.GET.get('event_type', '')
    f_severity = request.GET.get('severity', '')
    f_search = request.GET.get('search', '')
    f_date_from = request.GET.get('date_from', '')
    f_date_to = request.GET.get('date_to', '')

    if f_event_type:
        qs = qs.filter(event_type=f_event_type)
    if f_severity:
        qs = qs.filter(severity=f_severity)
    if f_search:
        qs = qs.filter(
            models.Q(title__icontains=f_search) | models.Q(description__icontains=f_search)
        )
    if f_date_from:
        qs = qs.filter(timestamp__date__gte=f_date_from)
    if f_date_to:
        qs = qs.filter(timestamp__date__lte=f_date_to)

    logs = qs[:200]

    # Support highlight parameter for scroll-to-log
    highlight_id = None
    try:
        highlight_id = int(request.GET.get('highlight', ''))
    except (ValueError, TypeError):
        pass

    context = {
        'active_tab': 'logs',
        'active_sub': 'logs',
        'role': 'production_supervisor',
        'mode': 'ui',
        'logs': logs,
        'highlight_id': highlight_id,
        'filter_event_type': f_event_type,
        'filter_severity': f_severity,
        'filter_search': f_search,
        'filter_date_from': f_date_from,
        'filter_date_to': f_date_to,
    }
    return render(request, 'dashboard/production/logs.html', context)


def production_ready_delivery(request):
    redir = _require_production(request)
    if redir:
        return redir

    orders_qs = ManufacturingOrder.objects.filter(
        status='completed',
        quality='PASS',
    ).select_related(
        'delivery', 'delivery__warehouse', 'delivery__material', 'material',
    ).prefetch_related('scrap_events', 'logs').order_by('-created_at')

    # Build enriched order list with full history (same as production_orders)
    orders = []
    for o in orders_qs:
        d = o.delivery
        delivery_info = None
        if d:
            stored_slots = list(ShelfSlot.objects.filter(
                delivery=d, is_occupied=True
            ).values_list('shelf_id', flat=True).distinct())
            delivery_info = {
                'batch_id': d.batch_id,
                'manufacturer': d.manufacturer,
                'date': d.date,
                'quantity': d.quantity,
                'shelf_id': d.shelf_id,
                'status': d.status,
                'warehouse_name': d.warehouse.name if d.warehouse else '\u2014',
                'warehouse_code': d.warehouse.code if d.warehouse else '\u2014',
                'material_name': d.material.name if d.material else d.manufacturer,
                'stored_shelves': stored_slots,
                'stored_at': d.created_at,
            }
        order_logs = list(o.logs.order_by('timestamp').values(
            'timestamp', 'event_type', 'severity', 'title', 'description', 'id',
        ))
        delivery_logs = []
        if d:
            delivery_logs = list(GlobalLog.objects.filter(
                delivery=d
            ).order_by('timestamp').values(
                'timestamp', 'event_type', 'severity', 'title', 'description', 'id',
            ))
        scraps = list(o.scrap_events.order_by('created_at').values(
            'machine_name', 'machine_id', 'scrap_type', 'scrap_rate', 'created_at',
        ))
        # Check if already stored on a shelf as finished goods
        stored_on_shelf = ShelfSlot.objects.filter(
            manufacturing_order=o, is_occupied=True
        ).select_related('warehouse').first()

        orders.append({
            'order': o,
            'delivery_info': delivery_info,
            'order_logs': order_logs,
            'delivery_logs': delivery_logs,
            'scraps': scraps,
            'stage_data': o.stage_data or [],
            'stage_timestamps': o.stage_timestamps or [],
            'timeline': sorted(delivery_logs + order_logs, key=lambda x: x['timestamp']),
            'stored_on_shelf': stored_on_shelf,
        })

    warehouses = Warehouse.objects.all().order_by('id')

    context = {
        'active_tab': 'ready_delivery',
        'active_sub': 'ready_delivery',
        'role': 'production_supervisor',
        'mode': 'ui',
        'orders': orders,
        'warehouses': warehouses,
    }
    return render(request, 'dashboard/production/ready_delivery.html', context)


def production_warehouse_editor(request, warehouse_id):
    redir = _require_production(request)
    if redir:
        return redir
    try:
        wh = Warehouse.objects.get(id=warehouse_id)
    except Warehouse.DoesNotExist:
        from django.http import Http404
        raise Http404
    context = {
        'active_tab': 'warehouses',
        'active_sub': 'warehouses',
        'role': 'production_supervisor',
        'mode': 'ui',
        'warehouse': wh,
    }
    return render(request, 'dashboard/production/warehouse_editor.html', context)


def production_pipeline(request):
    redir = _require_production(request)
    if redir:
        return redir
    context = {
        'active_tab': 'pipeline',
        'active_sub': 'pipeline',
        'role': 'production_supervisor',
        'mode': 'ui',
        **_get_manufacturing_context(request, all_warehouses=True),
    }
    return render(request, 'dashboard/production/pipeline.html', context)
