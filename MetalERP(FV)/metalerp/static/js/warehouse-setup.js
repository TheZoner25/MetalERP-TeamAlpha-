/* ============================================
   Warehouse Layout Setup — Canvas Grid Editor
   ============================================ */
(function () {
    'use strict';

    // --- State ---
    var grid = [];          // 2D array: grid[row][col] = { cell_type, label, sector, unit }
    var rows = 0, cols = 0;
    var activeTool = null;  // 'wall' | 'storage' | 'walkway' | 'dock' | 'empty' | null
    var isPainting = false;
    var currentShape = 'rectangle';

    // --- Canvas ---
    var canvas = document.getElementById('gridCanvas');
    var ctx = canvas.getContext('2d');
    var wrap = document.getElementById('gridEditorWrap');
    var cellSize = 40;      // px per cell (recalculated on render)
    var offsetX = 0, offsetY = 0;  // pan offset
    var scale = 1;
    var lastPinchDist = 0;

    // --- Colors ---
    var COLORS = {
        storage:  '#5B8DEF',
        wall:     '#444444',
        walkway:  '#D4D4D4',
        dock:     '#E8943A',
        empty:    '#F5F5F8',
    };
    var BORDER = '#CCCCCC';
    var LABEL_COLOR = '#FFFFFF';

    // ---- Init ----
    function init() {
        bindShapeSelector();
        bindToolbar();
        bindCanvasEvents();
        document.getElementById('generateBtn').addEventListener('click', generateGrid);
        document.getElementById('saveLayoutBtn').addEventListener('click', saveLayout);
        document.getElementById('autoAssignBtn').addEventListener('click', autoAssign);

        // Load existing layout
        loadExisting();
    }

    // ---- Load existing layout from server ----
    function loadExisting() {
        fetch('/api/warehouse-layout/' + WAREHOUSE_ID + '/')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.cells && data.cells.length > 0) {
                    rows = data.grid_rows;
                    cols = data.grid_cols;
                    currentShape = data.shape || 'rectangle';
                    // Set form values
                    document.getElementById('widthInput').value = data.width_m;
                    document.getElementById('lengthInput').value = data.length_m;
                    document.getElementById('heightInput').value = data.height_m;
                    document.getElementById('gridRowsInput').value = rows;
                    document.getElementById('gridColsInput').value = cols;
                    document.getElementById('shelvesInput').value = data.shelves_per_unit;
                    document.getElementById('slotsInput').value = data.slots_per_shelf;
                    // Set shape button
                    setActiveShape(currentShape);
                    // Build grid from cells
                    buildEmptyGrid();
                    data.cells.forEach(function (c) {
                        if (c.row < rows && c.col < cols) {
                            grid[c.row][c.col] = {
                                cell_type: c.cell_type,
                                label: c.label || '',
                                sector: c.sector,
                                unit: c.unit || '',
                            };
                        }
                    });
                    render();
                    document.getElementById('gridHint').textContent = 'Layout loaded. Use the toolbar to edit cells.';
                }
            })
            .catch(function () { /* no layout yet */ });
    }

    // ---- Shape selector ----
    function bindShapeSelector() {
        var btns = document.querySelectorAll('.shape-btn');
        btns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                currentShape = btn.dataset.shape;
                setActiveShape(currentShape);
            });
        });
    }

    function setActiveShape(shape) {
        document.querySelectorAll('.shape-btn').forEach(function (b) {
            b.classList.toggle('active', b.dataset.shape === shape);
        });
    }

    // ---- Toolbar ----
    function bindToolbar() {
        document.querySelectorAll('.tool-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var tool = btn.dataset.tool;
                if (activeTool === tool) {
                    activeTool = null;
                    btn.classList.remove('active');
                } else {
                    activeTool = tool;
                    document.querySelectorAll('.tool-btn').forEach(function (b) { b.classList.remove('active'); });
                    btn.classList.add('active');
                }
            });
        });
    }

    // ---- Generate grid ----
    function generateGrid() {
        rows = parseInt(document.getElementById('gridRowsInput').value) || 10;
        cols = parseInt(document.getElementById('gridColsInput').value) || 10;
        rows = Math.max(2, Math.min(50, rows));
        cols = Math.max(2, Math.min(50, cols));

        if (currentShape === 'circle') {
            // Fetch circle-clipped grid from backend
            fetch('/api/warehouse-layout/' + WAREHOUSE_ID + '/apply-shape/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                body: JSON.stringify({ shape: 'circle', grid_rows: rows, grid_cols: cols })
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                buildEmptyGrid();
                data.cells.forEach(function (c) {
                    if (c.row < rows && c.col < cols) {
                        grid[c.row][c.col].cell_type = c.cell_type;
                    }
                });
                render();
                document.getElementById('gridHint').textContent = 'Circle shape applied. Paint storage cells, then save.';
            });
        } else {
            buildEmptyGrid();
            render();
            var hint = currentShape === 'custom'
                ? 'Draw your warehouse outline using the Wall tool, then paint Storage cells.'
                : 'Grid generated. Paint cells using the toolbar, then save.';
            document.getElementById('gridHint').textContent = hint;
        }
    }

    function buildEmptyGrid() {
        grid = [];
        for (var r = 0; r < rows; r++) {
            var row = [];
            for (var c = 0; c < cols; c++) {
                row.push({ cell_type: 'empty', label: '', sector: null, unit: '' });
            }
            grid.push(row);
        }
        // Reset viewport
        scale = 1;
        offsetX = 0;
        offsetY = 0;
    }

    // ---- Render ----
    function render() {
        if (rows === 0 || cols === 0) return;

        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        var wrapW = wrap.clientWidth;
        var maxCellW = (wrapW - 20) / cols;
        cellSize = Math.max(28, Math.min(60, maxCellW));

        var totalW = cols * cellSize;
        var totalH = rows * cellSize;
        var canvasW = Math.max(wrapW, totalW + 20);
        var canvasH = Math.max(300, totalH + 20);

        canvas.width = canvasW * dpr;
        canvas.height = canvasH * dpr;
        canvas.style.width = canvasW + 'px';
        canvas.style.height = canvasH + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        // Clear
        ctx.clearRect(0, 0, canvasW, canvasH);

        // Apply transform
        ctx.save();
        ctx.translate(offsetX + 10, offsetY + 10);
        ctx.scale(scale, scale);

        // Draw cells
        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var cell = grid[r][c];
                var x = c * cellSize;
                var y = r * cellSize;

                // Fill
                ctx.fillStyle = COLORS[cell.cell_type] || COLORS.empty;
                ctx.fillRect(x, y, cellSize, cellSize);

                // Border
                ctx.strokeStyle = BORDER;
                ctx.lineWidth = 0.5;
                ctx.strokeRect(x, y, cellSize, cellSize);

                // Label
                if (cell.label && cellSize * scale >= 24) {
                    ctx.fillStyle = cell.cell_type === 'storage' ? LABEL_COLOR : '#333';
                    ctx.font = Math.max(8, cellSize * 0.25) + 'px DM Sans, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(cell.label, x + cellSize / 2, y + cellSize / 2);
                }
            }
        }

        ctx.restore();
    }

    // ---- Canvas events (mouse + touch) ----
    function bindCanvasEvents() {
        // Mouse
        canvas.addEventListener('mousedown', function (e) {
            if (!activeTool) return;
            isPainting = true;
            paintAt(e);
        });
        canvas.addEventListener('mousemove', function (e) {
            if (isPainting && activeTool) paintAt(e);
        });
        canvas.addEventListener('mouseup', function () { isPainting = false; });
        canvas.addEventListener('mouseleave', function () { isPainting = false; });

        // Touch
        canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
        canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
        canvas.addEventListener('touchend', handleTouchEnd, { passive: false });

        // Resize
        window.addEventListener('resize', function () { if (rows > 0) render(); });
    }

    function getCellAt(e) {
        var rect = canvas.getBoundingClientRect();
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        var mx = (e.clientX - rect.left - offsetX - 10) / scale;
        var my = (e.clientY - rect.top - offsetY - 10) / scale;
        var c = Math.floor(mx / cellSize);
        var r = Math.floor(my / cellSize);
        if (r >= 0 && r < rows && c >= 0 && c < cols) return { r: r, c: c };
        return null;
    }

    function paintAt(e) {
        var pos = getCellAt(e);
        if (!pos || !activeTool) return;
        var cell = grid[pos.r][pos.c];
        // Toggle behavior for wall tool
        if (activeTool === 'wall' && cell.cell_type === 'wall') {
            cell.cell_type = 'empty';
            cell.label = '';
            cell.sector = null;
            cell.unit = '';
        } else {
            cell.cell_type = activeTool;
            if (activeTool !== 'storage') {
                cell.label = '';
                cell.sector = null;
                cell.unit = '';
            }
        }
        render();
    }

    // ---- Touch handling ----
    var touchStartPos = null;

    function handleTouchStart(e) {
        e.preventDefault();
        if (e.touches.length === 2) {
            lastPinchDist = pinchDist(e.touches);
        } else if (e.touches.length === 1) {
            touchStartPos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
            if (activeTool) {
                isPainting = true;
                paintAtTouch(e.touches[0]);
            }
        }
    }

    function handleTouchMove(e) {
        e.preventDefault();
        if (e.touches.length === 2) {
            // Pinch zoom
            var dist = pinchDist(e.touches);
            var delta = dist / lastPinchDist;
            scale = Math.max(0.5, Math.min(3, scale * delta));
            lastPinchDist = dist;
            render();
        } else if (e.touches.length === 1) {
            if (activeTool && isPainting) {
                paintAtTouch(e.touches[0]);
            } else if (!activeTool && touchStartPos) {
                // Pan
                var dx = e.touches[0].clientX - touchStartPos.x;
                var dy = e.touches[0].clientY - touchStartPos.y;
                offsetX += dx;
                offsetY += dy;
                touchStartPos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
                render();
            }
        }
    }

    function handleTouchEnd(e) {
        e.preventDefault();
        isPainting = false;
        touchStartPos = null;
    }

    function paintAtTouch(touch) {
        var rect = canvas.getBoundingClientRect();
        var mx = (touch.clientX - rect.left - offsetX - 10) / scale;
        var my = (touch.clientY - rect.top - offsetY - 10) / scale;
        var c = Math.floor(mx / cellSize);
        var r = Math.floor(my / cellSize);
        if (r >= 0 && r < rows && c >= 0 && c < cols) {
            var cell = grid[r][c];
            if (activeTool === 'wall' && cell.cell_type === 'wall') {
                cell.cell_type = 'empty';
                cell.label = '';
                cell.sector = null;
                cell.unit = '';
            } else {
                cell.cell_type = activeTool;
                if (activeTool !== 'storage') {
                    cell.label = '';
                    cell.sector = null;
                    cell.unit = '';
                }
            }
            render();
        }
    }

    function pinchDist(touches) {
        var dx = touches[0].clientX - touches[1].clientX;
        var dy = touches[0].clientY - touches[1].clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    // ---- Save layout ----
    function saveLayout() {
        var cells = [];
        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var cell = grid[r][c];
                cells.push({
                    row: r, col: c,
                    cell_type: cell.cell_type,
                    label: cell.label,
                    sector: cell.sector,
                    unit: cell.unit,
                });
            }
        }
        var body = {
            shape: currentShape,
            width_m: parseFloat(document.getElementById('widthInput').value),
            length_m: parseFloat(document.getElementById('lengthInput').value),
            height_m: parseFloat(document.getElementById('heightInput').value),
            grid_rows: rows,
            grid_cols: cols,
            shelves_per_unit: parseInt(document.getElementById('shelvesInput').value),
            slots_per_shelf: parseInt(document.getElementById('slotsInput').value),
            cells: cells,
        };
        var btn = document.getElementById('saveLayoutBtn');
        btn.textContent = 'Saving...';
        btn.disabled = true;

        fetch('/api/warehouse-layout/' + WAREHOUSE_ID + '/save/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(body)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            btn.textContent = 'Saved!';
            setTimeout(function () { btn.textContent = 'Save Layout'; btn.disabled = false; }, 1500);
            document.getElementById('gridHint').textContent = 'Layout saved successfully.';
        })
        .catch(function () {
            btn.textContent = 'Save Layout';
            btn.disabled = false;
            alert('Error saving layout.');
        });
    }

    // ---- Auto-assign sectors ----
    function autoAssign() {
        var storageCount = 0;
        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                if (grid[r][c].cell_type === 'storage') storageCount++;
            }
        }
        if (storageCount === 0) {
            alert('No storage cells to assign. Paint some storage cells first.');
            return;
        }

        // First save current state, then auto-assign
        saveLayoutThen(function () {
            fetch('/api/warehouse-layout/' + WAREHOUSE_ID + '/auto-assign/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                body: '{}'
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.cells) {
                    data.cells.forEach(function (c) {
                        if (c.row < rows && c.col < cols) {
                            grid[c.row][c.col].label = c.label || '';
                            grid[c.row][c.col].sector = c.sector;
                            grid[c.row][c.col].unit = c.unit || '';
                        }
                    });
                    render();
                    document.getElementById('gridHint').textContent = 'Sectors auto-assigned. Save to persist.';
                }
            });
        });
    }

    function saveLayoutThen(callback) {
        var cells = [];
        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var cell = grid[r][c];
                cells.push({
                    row: r, col: c,
                    cell_type: cell.cell_type,
                    label: cell.label,
                    sector: cell.sector,
                    unit: cell.unit,
                });
            }
        }
        var body = {
            shape: currentShape,
            width_m: parseFloat(document.getElementById('widthInput').value),
            length_m: parseFloat(document.getElementById('lengthInput').value),
            height_m: parseFloat(document.getElementById('heightInput').value),
            grid_rows: rows,
            grid_cols: cols,
            shelves_per_unit: parseInt(document.getElementById('shelvesInput').value),
            slots_per_shelf: parseInt(document.getElementById('slotsInput').value),
            cells: cells,
        };
        fetch('/api/warehouse-layout/' + WAREHOUSE_ID + '/save/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(body)
        })
        .then(function (r) { return r.json(); })
        .then(callback);
    }

    // ---- Start ----
    init();
})();
