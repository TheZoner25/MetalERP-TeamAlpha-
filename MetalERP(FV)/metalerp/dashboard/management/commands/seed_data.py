import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from dashboard.models import Warehouse, Material, Delivery, ShelfSlot


MATERIALS = [
    ('HR Coil', 'Steel Sheet'),
    ('CR Sheet', 'Steel Sheet'),
    ('GP Sheet', 'Steel Sheet'),
    ('TMT Bar Fe-500', 'Bar & Rod'),
    ('MS Angle', 'Structural'),
    ('HR Plate', 'Steel Plate'),
    ('SS Sheet 304', 'Stainless Steel'),
    ('SS Sheet 316', 'Stainless Steel'),
    ('GI Pipe', 'Pipe & Tube'),
    ('MS Channel', 'Structural'),
    ('Aluminium Sheet', 'Non-Ferrous'),
    ('Copper Rod', 'Non-Ferrous'),
    ('MS Flat Bar', 'Bar & Rod'),
    ('Chequered Plate', 'Steel Plate'),
    ('Wire Rod', 'Bar & Rod'),
]

WAREHOUSES = [
    {'name': 'Main Warehouse', 'code': 'WH-01', 'num_docks': 3},
    {'name': 'East Wing', 'code': 'WH-02', 'num_docks': 5},
    {'name': 'Cold Storage', 'code': 'WH-03', 'num_docks': 4},
]

# Original deliveries for WH-01
WH01_DELIVERIES = [
    {'manufacturer': 'Tata Steel Ltd.',     'date': '2026-03-25', 'size': '2.5mm x 1250mm',  'batch_id': 'BATCH-TS-0412',   'quantity': '3', 'shelf_id': '1-A-3', 'material_idx': 0},
    {'manufacturer': 'JSW Steel',           'date': '2026-03-25', 'size': '1.2mm x 1000mm',  'batch_id': 'BATCH-JSW-0198',  'quantity': '4', 'shelf_id': '1-B-2', 'material_idx': 1},
    {'manufacturer': 'SAIL',                'date': '2026-03-24', 'size': '12mm dia',         'batch_id': 'BATCH-SAIL-0087', 'quantity': '2', 'shelf_id': '2-A-1', 'material_idx': 3},
    {'manufacturer': 'Hindalco Industries', 'date': '2026-03-24', 'size': '3mm x 1500mm',    'batch_id': 'BATCH-HIN-0234',  'quantity': '3', 'shelf_id': '2-C-4', 'material_idx': 0},
    {'manufacturer': 'Vedanta Resources',   'date': '2026-03-23', 'size': '25kg blocks',      'batch_id': 'BATCH-VED-0056',  'quantity': '4', 'shelf_id': '3-B-2', 'material_idx': 10},
    {'manufacturer': 'Tata Steel Ltd.',     'date': '2026-03-23', 'size': '0.5mm x 1250mm',  'batch_id': 'BATCH-TS-0413',   'quantity': '1', 'shelf_id': '3-D-1', 'material_idx': 2},
    {'manufacturer': 'Jindal Stainless',    'date': '2026-03-22', 'size': '2mm x 1220mm',    'batch_id': 'BATCH-JIN-0321',  'quantity': '2', 'shelf_id': '4-A-5', 'material_idx': 6},
    {'manufacturer': 'Hindalco Industries', 'date': '2026-03-22', 'size': '8mm dia',          'batch_id': 'BATCH-HIN-0235',  'quantity': '1', 'shelf_id': '4-B-3', 'material_idx': 3},
    {'manufacturer': 'JSW Steel',           'date': '2026-03-21', 'size': '50x50x6mm',        'batch_id': 'BATCH-JSW-0199',  'quantity': '4', 'shelf_id': '5-C-3', 'material_idx': 4},
    {'manufacturer': 'SAIL',                'date': '2026-03-21', 'size': '10mm x 2000mm',   'batch_id': 'BATCH-SAIL-0088', 'quantity': '3', 'shelf_id': '5-A-1', 'material_idx': 5},
    {'manufacturer': 'Tata Steel Ltd.',     'date': '2026-03-20', 'size': '1.6mm x 1250mm',  'batch_id': 'BATCH-TS-0414',   'quantity': '2', 'shelf_id': '6-B-1', 'material_idx': 1},
    {'manufacturer': 'Vedanta Resources',   'date': '2026-03-20', 'size': '50kg blocks',      'batch_id': 'BATCH-VED-0057',  'quantity': '2', 'shelf_id': '6-C-2', 'material_idx': 10},
    {'manufacturer': 'JSW Steel',           'date': '2026-03-19', 'size': '0.8mm x 1000mm',  'batch_id': 'BATCH-JSW-0200',  'quantity': '3', 'shelf_id': '7-A-2', 'material_idx': 2},
    {'manufacturer': 'Jindal Stainless',    'date': '2026-03-19', 'size': '1.5mm x 1220mm',  'batch_id': 'BATCH-JIN-0322',  'quantity': '1', 'shelf_id': '7-B-4', 'material_idx': 7},
    {'manufacturer': 'SAIL',                'date': '2026-03-18', 'size': '16mm dia',         'batch_id': 'BATCH-SAIL-0089', 'quantity': '4', 'shelf_id': '1-C-5', 'material_idx': 3},
    {'manufacturer': 'Tata Steel Ltd.',     'date': '2026-03-18', 'size': '6mm x 2000mm',    'batch_id': 'BATCH-TS-0415',   'quantity': '3', 'shelf_id': '2-B-6', 'material_idx': 5},
    {'manufacturer': 'Hindalco Industries', 'date': '2026-03-17', 'size': '4mm x 1500mm',    'batch_id': 'BATCH-HIN-0236',  'quantity': '2', 'shelf_id': '4-D-2', 'material_idx': 0},
    {'manufacturer': 'JSW Steel',           'date': '2026-03-17', 'size': '3.15mm x 1250mm', 'batch_id': 'BATCH-JSW-0201',  'quantity': '4', 'shelf_id': '5-B-1', 'material_idx': 1},
]

WH01_OCCUPANCY = {
    '1-A-1': [0, 1, 2, 3],
    '1-A-2': [0, 1],
    '1-B-3': [0, 2],
    '2-A-1': [0, 1, 2],
    '2-C-4': [0, 1, 2, 3],
    '3-B-2': [0, 3],
    '3-D-1': [0, 1, 2, 3],
    '4-A-5': [0, 1],
    '5-C-3': [0, 1, 2, 3],
    '6-B-1': [0],
    '7-A-2': [0, 1, 2, 3],
}

# Deliveries for WH-02 (East Wing)
WH02_DELIVERIES = [
    {'manufacturer': 'ArcelorMittal',       'date': '2026-03-26', 'size': '3.0mm x 1500mm',  'batch_id': 'BATCH-WH02-AM-0101',  'quantity': '4', 'shelf_id': '2-B-1', 'material_idx': 0},
    {'manufacturer': 'Nucor Corporation',   'date': '2026-03-26', 'size': '1.5mm x 1200mm',  'batch_id': 'BATCH-WH02-NC-0102',  'quantity': '2', 'shelf_id': '2-C-3', 'material_idx': 1},
    {'manufacturer': 'POSCO',               'date': '2026-03-25', 'size': '10mm dia',         'batch_id': 'BATCH-WH02-PO-0103',  'quantity': '3', 'shelf_id': '3-A-2', 'material_idx': 3},
    {'manufacturer': 'Baosteel',            'date': '2026-03-25', 'size': '2.0mm x 1250mm',  'batch_id': 'BATCH-WH02-BS-0104',  'quantity': '1', 'shelf_id': '3-D-5', 'material_idx': 2},
    {'manufacturer': 'ThyssenKrupp',        'date': '2026-03-24', 'size': '0.8mm x 1000mm',  'batch_id': 'BATCH-WH02-TK-0105',  'quantity': '4', 'shelf_id': '4-B-1', 'material_idx': 6},
    {'manufacturer': 'ArcelorMittal',       'date': '2026-03-24', 'size': '6mm x 2000mm',    'batch_id': 'BATCH-WH02-AM-0106',  'quantity': '3', 'shelf_id': '4-C-4', 'material_idx': 5},
    {'manufacturer': 'Nucor Corporation',   'date': '2026-03-23', 'size': '50x50x6mm',        'batch_id': 'BATCH-WH02-NC-0107',  'quantity': '2', 'shelf_id': '5-A-3', 'material_idx': 4},
    {'manufacturer': 'POSCO',               'date': '2026-03-23', 'size': '25kg blocks',      'batch_id': 'BATCH-WH02-PO-0108',  'quantity': '4', 'shelf_id': '5-B-6', 'material_idx': 10},
    {'manufacturer': 'Baosteel',            'date': '2026-03-22', 'size': '16mm dia',         'batch_id': 'BATCH-WH02-BS-0109',  'quantity': '2', 'shelf_id': '6-A-2', 'material_idx': 3},
    {'manufacturer': 'ThyssenKrupp',        'date': '2026-03-22', 'size': '4mm x 1500mm',    'batch_id': 'BATCH-WH02-TK-0110',  'quantity': '3', 'shelf_id': '6-D-1', 'material_idx': 0},
    {'manufacturer': 'ArcelorMittal',       'date': '2026-03-21', 'size': '1.2mm x 1000mm',  'batch_id': 'BATCH-WH02-AM-0111',  'quantity': '1', 'shelf_id': '7-B-3', 'material_idx': 1},
    {'manufacturer': 'Nucor Corporation',   'date': '2026-03-21', 'size': '3.15mm x 1250mm', 'batch_id': 'BATCH-WH02-NC-0112',  'quantity': '4', 'shelf_id': '7-C-5', 'material_idx': 14},
    {'manufacturer': 'POSCO',               'date': '2026-03-20', 'size': '2mm x 1220mm',    'batch_id': 'BATCH-WH02-PO-0113',  'quantity': '2', 'shelf_id': '1-A-4', 'material_idx': 7},
    {'manufacturer': 'Baosteel',            'date': '2026-03-20', 'size': '8mm dia',          'batch_id': 'BATCH-WH02-BS-0114',  'quantity': '3', 'shelf_id': '1-C-2', 'material_idx': 12},
    {'manufacturer': 'ThyssenKrupp',        'date': '2026-03-19', 'size': '50kg blocks',      'batch_id': 'BATCH-WH02-TK-0115',  'quantity': '1', 'shelf_id': '2-A-6', 'material_idx': 11},
    {'manufacturer': 'ArcelorMittal',       'date': '2026-03-19', 'size': '0.5mm x 1250mm',  'batch_id': 'BATCH-WH02-AM-0116',  'quantity': '4', 'shelf_id': '3-B-1', 'material_idx': 2},
    {'manufacturer': 'Nucor Corporation',   'date': '2026-03-18', 'size': '10mm x 2000mm',   'batch_id': 'BATCH-WH02-NC-0117',  'quantity': '2', 'shelf_id': '4-A-3', 'material_idx': 5},
    {'manufacturer': 'POSCO',               'date': '2026-03-18', 'size': '1.6mm x 1250mm',  'batch_id': 'BATCH-WH02-PO-0118',  'quantity': '3', 'shelf_id': '5-D-2', 'material_idx': 1},
    {'manufacturer': 'Baosteel',            'date': '2026-03-17', 'size': '12mm dia',         'batch_id': 'BATCH-WH02-BS-0119',  'quantity': '4', 'shelf_id': '6-B-4', 'material_idx': 3},
    {'manufacturer': 'ThyssenKrupp',        'date': '2026-03-17', 'size': '2.5mm x 1250mm',  'batch_id': 'BATCH-WH02-TK-0120',  'quantity': '2', 'shelf_id': '7-A-1', 'material_idx': 13},
]

WH02_OCCUPANCY = {
    '2-B-1': [0, 1, 2, 3],
    '2-C-3': [0, 1],
    '3-A-2': [0, 1, 2],
    '4-B-1': [0, 1, 2, 3],
    '4-C-4': [0, 1, 2],
    '5-A-3': [0, 1],
    '5-B-6': [0, 1, 2, 3],
    '6-A-2': [0, 1],
    '6-D-1': [0, 1, 2],
    '7-B-3': [0],
    '7-C-5': [0, 1, 2, 3],
    '1-A-4': [0, 1],
    '1-C-2': [0, 1, 2],
}

# Deliveries for WH-03 (Cold Storage)
WH03_DELIVERIES = [
    {'manufacturer': 'Gerdau',              'date': '2026-03-26', 'size': '1.0mm x 1000mm',  'batch_id': 'BATCH-WH03-GD-0201',  'quantity': '3', 'shelf_id': '1-B-4', 'material_idx': 8},
    {'manufacturer': 'Nippon Steel',        'date': '2026-03-25', 'size': '2.5mm x 1250mm',  'batch_id': 'BATCH-WH03-NS-0202',  'quantity': '2', 'shelf_id': '1-D-1', 'material_idx': 0},
    {'manufacturer': 'Ternium',             'date': '2026-03-25', 'size': '0.5mm x 1250mm',  'batch_id': 'BATCH-WH03-TN-0203',  'quantity': '4', 'shelf_id': '2-A-3', 'material_idx': 2},
    {'manufacturer': 'Gerdau',              'date': '2026-03-24', 'size': '12mm dia',         'batch_id': 'BATCH-WH03-GD-0204',  'quantity': '1', 'shelf_id': '2-B-5', 'material_idx': 3},
    {'manufacturer': 'Nippon Steel',        'date': '2026-03-24', 'size': '3mm x 1500mm',    'batch_id': 'BATCH-WH03-NS-0205',  'quantity': '3', 'shelf_id': '3-C-1', 'material_idx': 0},
    {'manufacturer': 'Ternium',             'date': '2026-03-23', 'size': '50x50x6mm',        'batch_id': 'BATCH-WH03-TN-0206',  'quantity': '2', 'shelf_id': '3-D-4', 'material_idx': 9},
    {'manufacturer': 'Gerdau',              'date': '2026-03-23', 'size': '8mm dia',          'batch_id': 'BATCH-WH03-GD-0207',  'quantity': '4', 'shelf_id': '4-A-2', 'material_idx': 3},
    {'manufacturer': 'Nippon Steel',        'date': '2026-03-22', 'size': '6mm x 2000mm',    'batch_id': 'BATCH-WH03-NS-0208',  'quantity': '1', 'shelf_id': '4-C-6', 'material_idx': 5},
    {'manufacturer': 'Ternium',             'date': '2026-03-22', 'size': '25kg blocks',      'batch_id': 'BATCH-WH03-TN-0209',  'quantity': '3', 'shelf_id': '5-B-3', 'material_idx': 10},
    {'manufacturer': 'Gerdau',              'date': '2026-03-21', 'size': '1.5mm x 1220mm',  'batch_id': 'BATCH-WH03-GD-0210',  'quantity': '2', 'shelf_id': '5-D-1', 'material_idx': 7},
    {'manufacturer': 'Nippon Steel',        'date': '2026-03-21', 'size': '4mm x 1500mm',    'batch_id': 'BATCH-WH03-NS-0211',  'quantity': '4', 'shelf_id': '6-A-5', 'material_idx': 0},
    {'manufacturer': 'Ternium',             'date': '2026-03-20', 'size': '16mm dia',         'batch_id': 'BATCH-WH03-TN-0212',  'quantity': '1', 'shelf_id': '6-C-3', 'material_idx': 3},
    {'manufacturer': 'Gerdau',              'date': '2026-03-20', 'size': '2mm x 1220mm',    'batch_id': 'BATCH-WH03-GD-0213',  'quantity': '3', 'shelf_id': '7-B-2', 'material_idx': 6},
    {'manufacturer': 'Nippon Steel',        'date': '2026-03-19', 'size': '10mm x 2000mm',   'batch_id': 'BATCH-WH03-NS-0214',  'quantity': '2', 'shelf_id': '7-D-4', 'material_idx': 5},
    {'manufacturer': 'Ternium',             'date': '2026-03-18', 'size': '3.15mm x 1250mm', 'batch_id': 'BATCH-WH03-TN-0215',  'quantity': '4', 'shelf_id': '1-A-6', 'material_idx': 14},
]

WH03_OCCUPANCY = {
    '1-B-4': [0, 1, 2],
    '1-D-1': [0, 1],
    '2-A-3': [0, 1, 2, 3],
    '3-C-1': [0, 1, 2],
    '3-D-4': [0, 1],
    '4-A-2': [0, 1, 2, 3],
    '5-B-3': [0, 1, 2],
    '5-D-1': [0, 1],
    '6-A-5': [0, 1, 2, 3],
    '7-B-2': [0, 1, 2],
}

WAREHOUSE_DATA = [
    {'config': WAREHOUSES[0], 'deliveries': WH01_DELIVERIES, 'occupancy': WH01_OCCUPANCY},
    {'config': WAREHOUSES[1], 'deliveries': WH02_DELIVERIES, 'occupancy': WH02_OCCUPANCY},
    {'config': WAREHOUSES[2], 'deliveries': WH03_DELIVERIES, 'occupancy': WH03_OCCUPANCY},
]


class Command(BaseCommand):
    help = 'Seed the database with warehouses, materials, deliveries, and shelf occupancy'

    def handle(self, *args, **options):
        # Materials (global)
        material_objs = []
        for name, category in MATERIALS:
            obj, created = Material.objects.get_or_create(name=name, defaults={'category': category})
            material_objs.append(obj)
            if created:
                self.stdout.write(f'  Created material: {obj}')

        # Warehouses + per-warehouse data
        for wh_data in WAREHOUSE_DATA:
            cfg = wh_data['config']
            warehouse, created = Warehouse.objects.get_or_create(
                code=cfg['code'],
                defaults={'name': cfg['name'], 'num_docks': cfg['num_docks']},
            )
            if created:
                self.stdout.write(f'  Created warehouse: {warehouse}')

            # Deliveries
            for d in wh_data['deliveries']:
                mat = material_objs[d['material_idx']]
                obj, created = Delivery.objects.get_or_create(
                    batch_id=d['batch_id'],
                    defaults={
                        'manufacturer': d['manufacturer'],
                        'date': date.fromisoformat(d['date']),
                        'size': d['size'],
                        'quantity': d['quantity'],
                        'shelf_id': d['shelf_id'],
                        'status': 'pending',
                        'material': mat,
                        'warehouse': warehouse,
                    },
                )
                if created:
                    self.stdout.write(f'  [{cfg["code"]}] Created delivery: {obj}')

            # Shelf occupancy
            for shelf_id, slots in wh_data['occupancy'].items():
                for slot_idx in slots:
                    obj, created = ShelfSlot.objects.get_or_create(
                        warehouse=warehouse,
                        shelf_id=shelf_id,
                        slot_index=slot_idx,
                        defaults={'is_occupied': True},
                    )
                    if created:
                        self.stdout.write(f'  [{cfg["code"]}] Created slot: {obj}')

        self.stdout.write(self.style.SUCCESS('Seed data loaded successfully.'))
