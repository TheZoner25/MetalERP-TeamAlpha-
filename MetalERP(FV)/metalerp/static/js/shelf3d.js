/**
 * shelf3d.js — Three.js 3D Shelf Visualization + 2D Top-Down View
 * Single row (1×4) layout for steel sheet storage.
 */

(function () {
    'use strict';

    var scene, camera, renderer, controls, animationId;
    var shelfGroup;
    var currentShelfId = null;
    var currentTargetShelf = 1;
    var currentAllLevels = null;
    var currentDeliveryId = null;
    var currentMOId = null;        // Manufacturing order ID for finished goods storage
    var currentMOWarehouseId = null; // Warehouse ID for finished goods storage
    var slotMeshes = [];
    var topdownAnimId = null;

    // Light-mode colors
    var METAL_COLOR = 0x666666;
    var PALLET_COLOR = 0x888888;
    var EMPTY_COLOR = 0xdddddd;
    var HIGHLIGHT_COLOR = 0x333333;
    var GROUND_COLOR = 0xf0f0f0;
    var BG_COLOR = 0xf5f5f7;
    var BACK_PANEL_COLOR = 0xe0e0e0;
    var HIGHLIGHT_SHELF_COLOR = 0xcccccc;

    // Shelf geometry — steel sheet proportions (updated dynamically from API)
    var NUM_SHELVES = 6;
    var LEVEL_HEIGHT = 0.9;
    var SHELF_HEIGHT = NUM_SHELVES * LEVEL_HEIGHT;
    var SHELF_WIDTH = 10;
    var SHELF_DEPTH = 2.4;
    var UPRIGHT_WIDTH = 0.1;
    var SHELF_THICKNESS = 0.04;
    var COLS = 4;
    var ROWS_PER_SHELF = 1;
    var SLOTS_PER_SHELF = ROWS_PER_SHELF * COLS; // 4

    function updateShelfConfig(data) {
        if (data.shelves_per_unit && data.shelves_per_unit !== NUM_SHELVES) {
            NUM_SHELVES = data.shelves_per_unit;
            SHELF_HEIGHT = NUM_SHELVES * LEVEL_HEIGHT;
        }
        if (data.slots_per_shelf && data.slots_per_shelf !== COLS) {
            COLS = data.slots_per_shelf;
            SLOTS_PER_SHELF = ROWS_PER_SHELF * COLS;
        }
    }
    // Steel sheets: wide, very thin, deep — single row fills depth
    var PALLET_W = 2.0;
    var PALLET_H = 0.15;
    var PALLET_D = 2.0;
    var GAP = 0.12;

    // ========================================
    // Scene Setup
    // ========================================

    function initScene(container) {
        var w = container.clientWidth;
        var h = container.clientHeight;

        scene = new THREE.Scene();
        scene.background = new THREE.Color(BG_COLOR);
        scene.fog = new THREE.Fog(BG_COLOR, 18, 40);

        camera = new THREE.PerspectiveCamera(40, w / h, 0.1, 100);
        camera.position.set(9, 5, 10);
        camera.lookAt(0, SHELF_HEIGHT / 2, 0);

        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
        renderer.setSize(w, h);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 0.95;
        container.appendChild(renderer.domElement);

        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.maxPolarAngle = Math.PI / 2;
        controls.minDistance = 6;
        controls.maxDistance = 25;
        controls.target.set(0, SHELF_HEIGHT / 2, 0);
        controls.update();

        var ambient = new THREE.AmbientLight(0xffffff, 0.5);
        scene.add(ambient);

        var dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(5, 12, 6);
        dirLight.castShadow = true;
        dirLight.shadow.mapSize.width = 1024;
        dirLight.shadow.mapSize.height = 1024;
        dirLight.shadow.camera.near = 0.5;
        dirLight.shadow.camera.far = 35;
        dirLight.shadow.camera.left = -12;
        dirLight.shadow.camera.right = 12;
        dirLight.shadow.camera.top = 10;
        dirLight.shadow.camera.bottom = -4;
        dirLight.shadow.bias = -0.002;
        scene.add(dirLight);

        var rimLight = new THREE.DirectionalLight(0xffffff, 0.2);
        rimLight.position.set(-4, 3, -3);
        scene.add(rimLight);

        var groundGeo = new THREE.PlaneGeometry(30, 30);
        var groundMat = new THREE.MeshStandardMaterial({ color: GROUND_COLOR, roughness: 0.95, metalness: 0.0 });
        var ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.receiveShadow = true;
        scene.add(ground);

        var resizeHandler = function () {
            var w2 = container.clientWidth;
            var h2 = container.clientHeight;
            if (w2 > 0 && h2 > 0) {
                camera.aspect = w2 / h2;
                camera.updateProjectionMatrix();
                renderer.setSize(w2, h2);
            }
        };
        window.addEventListener('resize', resizeHandler);
        container._resizeHandler = resizeHandler;
    }

    // ========================================
    // Build Shelf Structure (6 shelves)
    // ========================================

    function buildShelf(targetShelf) {
        shelfGroup = new THREE.Group();

        var metalMat = new THREE.MeshStandardMaterial({ color: METAL_COLOR, roughness: 0.4, metalness: 0.7 });

        // Four uprights
        var uprightGeo = new THREE.BoxGeometry(UPRIGHT_WIDTH, SHELF_HEIGHT, UPRIGHT_WIDTH);
        [
            [-SHELF_WIDTH / 2, SHELF_HEIGHT / 2, -SHELF_DEPTH / 2],
            [SHELF_WIDTH / 2, SHELF_HEIGHT / 2, -SHELF_DEPTH / 2],
            [-SHELF_WIDTH / 2, SHELF_HEIGHT / 2, SHELF_DEPTH / 2],
            [SHELF_WIDTH / 2, SHELF_HEIGHT / 2, SHELF_DEPTH / 2]
        ].forEach(function (p) {
            var upright = new THREE.Mesh(uprightGeo, metalMat);
            upright.position.set(p[0], p[1], p[2]);
            upright.castShadow = true;
            shelfGroup.add(upright);
        });

        // Shelf planes
        var shelfGeo = new THREE.BoxGeometry(SHELF_WIDTH + UPRIGHT_WIDTH, SHELF_THICKNESS, SHELF_DEPTH + UPRIGHT_WIDTH);
        for (var i = 0; i <= NUM_SHELVES; i++) {
            var shelf = new THREE.Mesh(shelfGeo, metalMat);
            shelf.position.set(0, i * LEVEL_HEIGHT, 0);
            shelf.castShadow = true;
            shelf.receiveShadow = true;
            shelfGroup.add(shelf);
        }

        // Back panel — FrontSide only + depthWrite false to fix transparency glitch
        var backGeo = new THREE.PlaneGeometry(SHELF_WIDTH, SHELF_HEIGHT);
        var backMat = new THREE.MeshStandardMaterial({
            color: BACK_PANEL_COLOR, roughness: 0.8, metalness: 0.2,
            transparent: true, opacity: 0.25, side: THREE.FrontSide,
            depthWrite: false
        });
        var back = new THREE.Mesh(backGeo, backMat);
        back.position.set(0, SHELF_HEIGHT / 2, -SHELF_DEPTH / 2 - 0.01);
        back.renderOrder = 1;
        shelfGroup.add(back);

        // Cross braces
        var braceMat = new THREE.MeshStandardMaterial({ color: METAL_COLOR, roughness: 0.5, metalness: 0.6 });
        var braceGeo = new THREE.BoxGeometry(0.03, SHELF_HEIGHT * 1.05, 0.03);
        [-1, 1].forEach(function (dir) {
            var brace = new THREE.Mesh(braceGeo, braceMat);
            brace.position.set(0, SHELF_HEIGHT / 2, -SHELF_DEPTH / 2 - 0.02);
            brace.rotation.z = dir * 0.18;
            shelfGroup.add(brace);
        });

        // Highlight the target shelf level — depthWrite false
        if (targetShelf >= 1 && targetShelf <= NUM_SHELVES) {
            var highlightY = (targetShelf - 1) * LEVEL_HEIGHT + LEVEL_HEIGHT / 2;
            var highlightGeo = new THREE.BoxGeometry(SHELF_WIDTH - 0.08, LEVEL_HEIGHT - SHELF_THICKNESS * 2, SHELF_DEPTH - 0.08);
            var highlightMat = new THREE.MeshStandardMaterial({
                color: HIGHLIGHT_SHELF_COLOR, transparent: true, opacity: 0.1,
                roughness: 1, metalness: 0, depthWrite: false
            });
            var highlight = new THREE.Mesh(highlightGeo, highlightMat);
            highlight.position.set(0, highlightY, 0);
            highlight.renderOrder = 2;
            shelfGroup.add(highlight);
        }

        // Shelf number labels
        for (var s = 1; s <= NUM_SHELVES; s++) {
            var labelY = (s - 1) * LEVEL_HEIGHT + LEVEL_HEIGHT / 2;
            var canvas = document.createElement('canvas');
            canvas.width = 64;
            canvas.height = 32;
            var ctx = canvas.getContext('2d');
            ctx.fillStyle = s === targetShelf ? '#1A1A1A' : '#aaaaaa';
            ctx.font = (s === targetShelf ? 'bold ' : '') + '18px DM Sans, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('S' + s, 32, 16);
            var texture = new THREE.CanvasTexture(canvas);
            var spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true });
            var sprite = new THREE.Sprite(spriteMat);
            sprite.position.set(-SHELF_WIDTH / 2 - 0.5, labelY, 0);
            sprite.scale.set(0.7, 0.35, 1);
            shelfGroup.add(sprite);
        }

        scene.add(shelfGroup);
    }

    // ========================================
    // Place static pallets on OTHER levels (non-interactive, just visual)
    // ========================================

    function placeOtherLevelPallets(allLevels, targetShelf) {
        if (!allLevels) return;
        var startX = -SHELF_WIDTH / 2 + PALLET_W / 2 + GAP + UPRIGHT_WIDTH;
        var stepX = (SHELF_WIDTH - PALLET_W - 2 * GAP - 2 * UPRIGHT_WIDTH) / (COLS - 1);
        var palletDepth = PALLET_D * 0.85;
        var otherPalletColor = 0x999999;
        var otherRecentColor = 0x4a9eff;

        for (var level = 1; level <= NUM_SHELVES; level++) {
            if (level === targetShelf) continue;  // Skip target — handled by placePallets
            var levelData = allLevels[String(level)];
            if (!levelData || !levelData.occupied_slots || levelData.occupied_slots.length === 0) continue;

            var baseY = (level - 1) * LEVEL_HEIGHT + SHELF_THICKNESS;
            var recentSlots = levelData.recently_stored || [];

            for (var col = 0; col < COLS; col++) {
                if (levelData.occupied_slots.indexOf(col) === -1) continue;
                var isRecent = recentSlots.indexOf(col) !== -1;
                var x = startX + col * stepX;
                var y = baseY + PALLET_H / 2;

                var geo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                var color = isRecent ? otherRecentColor : otherPalletColor;
                var mat = new THREE.MeshStandardMaterial({
                    color: color, roughness: 0.5, metalness: 0.15,
                    transparent: true, opacity: 0.7
                });
                if (isRecent) {
                    mat.emissive = new THREE.Color(otherRecentColor);
                    mat.emissiveIntensity = 0.15;
                }
                var mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(x, y, 0);
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                scene.add(mesh);
                otherLevelMeshes.push(mesh);
            }
        }
    }

    // ========================================
    // Place Pallets on Target Shelf (1 row × 4 cols)
    // ========================================

    function placePallets(occupiedSlots, nextAvailable, targetShelf, recentlyStored) {
        slotMeshes = [];
        var startX = -SHELF_WIDTH / 2 + PALLET_W / 2 + GAP + UPRIGHT_WIDTH;
        var stepX = (SHELF_WIDTH - PALLET_W - 2 * GAP - 2 * UPRIGHT_WIDTH) / (COLS - 1);
        var baseShelfY = (targetShelf - 1) * LEVEL_HEIGHT + SHELF_THICKNESS;
        var recentSlots = recentlyStored || [];

        // Single row centered at z=0
        for (var col = 0; col < COLS; col++) {
            var slotIndex = col;
            var isOccupied = occupiedSlots.indexOf(slotIndex) !== -1;
            var isNext = slotIndex === nextAvailable;
            var isRecent = recentSlots.indexOf(slotIndex) !== -1;

            var x = startX + col * stepX;
            var y = baseShelfY + PALLET_H / 2;
            var z = 0;

            var palletDepth = PALLET_D * 0.85;
            var mesh;
            if (isOccupied) {
                var palletGeo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                if (isRecent) {
                    var glowMat = new THREE.MeshStandardMaterial({
                        color: 0x4a9eff, roughness: 0.3, metalness: 0.2,
                        emissive: new THREE.Color(0x4a9eff), emissiveIntensity: 0.3
                    });
                    mesh = new THREE.Mesh(palletGeo, glowMat);
                    mesh.userData.isNewlyStored = true;
                    mesh.userData.glowStart = performance.now();
                } else {
                    var palletMat = new THREE.MeshStandardMaterial({ color: PALLET_COLOR, roughness: 0.5, metalness: 0.2 });
                    mesh = new THREE.Mesh(palletGeo, palletMat);
                }
                mesh.castShadow = true;
                mesh.receiveShadow = true;
            } else if (isNext) {
                var hGeo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                var hMat = new THREE.MeshStandardMaterial({
                    color: HIGHLIGHT_COLOR, roughness: 0.3, metalness: 0.1,
                    emissive: new THREE.Color(HIGHLIGHT_COLOR), emissiveIntensity: 0.15,
                    transparent: true, opacity: 0.7, depthWrite: false
                });
                mesh = new THREE.Mesh(hGeo, hMat);
                mesh.castShadow = true;
                mesh.userData.isHighlight = true;
                mesh.renderOrder = 2;
            } else {
                var wGeo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                var wMat = new THREE.MeshBasicMaterial({
                    color: EMPTY_COLOR, wireframe: true,
                    transparent: true, opacity: 0.35, depthWrite: false
                });
                mesh = new THREE.Mesh(wGeo, wMat);
                mesh.renderOrder = 1;
            }

            mesh.position.set(x, y, z);
            mesh.userData.slotIndex = slotIndex;
            slotMeshes.push(mesh);
            scene.add(mesh);
        }
    }

    // ========================================
    // Animation Loop
    // ========================================

    var pulseTime = 0;

    function animate() {
        animationId = requestAnimationFrame(animate);
        pulseTime += 0.03;

        var now = performance.now();
        slotMeshes.forEach(function (m) {
            if (m.userData.isHighlight) {
                m.material.emissiveIntensity = 0.08 + Math.sin(pulseTime * 2) * 0.08;
                m.material.opacity = 0.5 + Math.sin(pulseTime * 2) * 0.2;
            }
            // Newly stored glow: fade from blue to normal over 60s
            if (m.userData.isNewlyStored) {
                var elapsed = (now - m.userData.glowStart) / 1000; // seconds
                var glowDuration = 60;
                var fade = Math.max(0, 1 - elapsed / glowDuration);
                m.material.emissiveIntensity = 0.3 * fade;
                if (fade <= 0) {
                    m.material.color.setHex(PALLET_COLOR);
                    m.material.emissive.setHex(0x000000);
                    m.material.emissiveIntensity = 0;
                    m.userData.isNewlyStored = false;
                }
            }
        });

        controls.update();
        renderer.render(scene, camera);
    }

    // ========================================
    // Top-Down 2D Canvas (1 row × 4 cols)
    // ========================================

    var topdownPulseTime = 0;

    function drawTopDown(canvas, occupiedSlots, nextAvailable, targetShelf, sector, unit, recentlyStored) {
        var parent = canvas.parentElement;
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        var w = parent.clientWidth;
        var h = parent.clientHeight;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';

        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        ctx.fillStyle = '#F5F5F7';
        ctx.fillRect(0, 0, w, h);

        // Title
        ctx.fillStyle = '#1A1A1A';
        ctx.font = 'bold 13px DM Sans, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Sector ' + sector + ' \u00B7 Unit ' + unit, w / 2, 42);

        ctx.fillStyle = '#999';
        ctx.font = '11px DM Sans, system-ui, sans-serif';
        ctx.fillText('Shelf ' + targetShelf + ' \u2014 Top View', w / 2, 60);

        // Grid — single row
        var gridPadding = 24;
        var gridTop = 85;
        var cellW = (w - gridPadding * 2) / COLS;
        var cellH = Math.min(cellW * 1.2, h - gridTop - 80);
        var gridW = cellW * COLS;
        var offsetX = (w - gridW) / 2;
        var offsetY = gridTop;

        // Display columns left to right: C1, C2, C3, C4
        var displayOrder = [0, 1, 2, 3];

        for (var vi = 0; vi < COLS; vi++) {
            var slotIndex = displayOrder[vi];
            var isOccupied = occupiedSlots.indexOf(slotIndex) !== -1;
            var isNext = slotIndex === nextAvailable;

            var cx = offsetX + vi * cellW;
            var cy = offsetY;
            var pad = 4;

            ctx.beginPath();
            roundRect(ctx, cx + pad, cy + pad, cellW - pad * 2, cellH - pad * 2, 6);

            var isRecent = recentlyStored && recentlyStored.indexOf(slotIndex) !== -1;

            if (isOccupied && isRecent) {
                ctx.fillStyle = '#4a9eff';
                ctx.fill();
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 11px DM Sans, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('P' + (slotIndex + 1), cx + cellW / 2, cy + cellH / 2);
            } else if (isOccupied) {
                ctx.fillStyle = '#888888';
                ctx.fill();
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 11px DM Sans, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('P' + (slotIndex + 1), cx + cellW / 2, cy + cellH / 2);
            } else if (isNext) {
                var alpha = 0.4 + Math.sin(topdownPulseTime * 2) * 0.3;
                ctx.fillStyle = 'rgba(26, 26, 26, ' + alpha.toFixed(2) + ')';
                ctx.fill();
                ctx.strokeStyle = '#1A1A1A';
                ctx.lineWidth = 2;
                ctx.stroke();
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 10px DM Sans, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('NEXT', cx + cellW / 2, cy + cellH / 2);
            } else {
                ctx.strokeStyle = 'rgba(0, 0, 0, 0.12)';
                ctx.lineWidth = 1;
                ctx.stroke();
                ctx.fillStyle = '#ccc';
                ctx.font = '10px DM Sans, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(slotIndex + 1, cx + cellW / 2, cy + cellH / 2);
            }
        }

        // Column labels (match center-out display order)
        ctx.fillStyle = '#999';
        ctx.font = '9px DM Sans, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (var c = 0; c < COLS; c++) {
            ctx.fillText('C' + (displayOrder[c] + 1), offsetX + c * cellW + cellW / 2, offsetY + cellH + 8);
        }

        // Legend
        var legendY = offsetY + cellH + 32;
        if (legendY + 20 < h) {
            var legendItems = [
                { color: '#888888', label: 'Occupied' },
                { color: '#4a9eff', label: 'New' },
                { color: '#1A1A1A', label: 'Next Slot' },
            ];
            var legendX = (w - legendItems.length * 90) / 2;
            legendItems.forEach(function (item, i) {
                ctx.fillStyle = item.color;
                ctx.beginPath();
                roundRect(ctx, legendX + i * 90, legendY, 12, 12, 2);
                ctx.fill();
                ctx.fillStyle = '#999';
                ctx.font = '9px DM Sans, system-ui, sans-serif';
                ctx.textAlign = 'left';
                ctx.textBaseline = 'middle';
                ctx.fillText(item.label, legendX + i * 90 + 16, legendY + 6);
            });
        }
    }

    function roundRect(ctx, x, y, w, h, r) {
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }

    function animateTopDown(canvas, occupiedSlots, nextAvailable, targetShelf, sector, unit, recentlyStored) {
        topdownPulseTime += 0.03;
        drawTopDown(canvas, occupiedSlots, nextAvailable, targetShelf, sector, unit, recentlyStored);
        topdownAnimId = requestAnimationFrame(function () {
            animateTopDown(canvas, occupiedSlots, nextAvailable, targetShelf, sector, unit, recentlyStored);
        });
    }

    // ========================================
    // Rebuild Slots After Store (keeps 3D in sync)
    // ========================================

    // Track other-level pallet meshes so we can remove them on rebuild
    var otherLevelMeshes = [];

    function removeOtherLevelPallets() {
        otherLevelMeshes.forEach(function (m) {
            scene.remove(m);
            if (m.geometry) m.geometry.dispose();
            if (m.material) m.material.dispose();
        });
        otherLevelMeshes = [];
    }

    function rebuildSlots(occupiedSlots, nextAvailable, targetShelf, justStoredSlot) {
        // Remove old slot meshes from scene
        slotMeshes.forEach(function (m) {
            scene.remove(m);
            if (m.geometry) m.geometry.dispose();
            if (m.material) m.material.dispose();
        });
        slotMeshes = [];

        var startX = -SHELF_WIDTH / 2 + PALLET_W / 2 + GAP + UPRIGHT_WIDTH;
        var stepX = (SHELF_WIDTH - PALLET_W - 2 * GAP - 2 * UPRIGHT_WIDTH) / (COLS - 1);
        var baseShelfY = (targetShelf - 1) * LEVEL_HEIGHT + SHELF_THICKNESS;
        var palletDepth = PALLET_D * 0.85;

        for (var col = 0; col < COLS; col++) {
            var slotIndex = col;
            var isOccupied = occupiedSlots.indexOf(slotIndex) !== -1;
            var isNext = slotIndex === nextAvailable;
            var justStored = slotIndex === justStoredSlot;

            var x = startX + col * stepX;
            var y = baseShelfY + PALLET_H / 2;
            var z = 0;

            var mesh;
            if (isOccupied) {
                var palletGeo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                if (justStored) {
                    // Glow effect for just-stored pallet
                    var glowMat = new THREE.MeshStandardMaterial({
                        color: 0x4a9eff, roughness: 0.3, metalness: 0.2,
                        emissive: new THREE.Color(0x4a9eff), emissiveIntensity: 0.3
                    });
                    mesh = new THREE.Mesh(palletGeo, glowMat);
                    mesh.userData.isNewlyStored = true;
                    mesh.userData.glowStart = performance.now();
                } else {
                    var palletMat = new THREE.MeshStandardMaterial({ color: PALLET_COLOR, roughness: 0.5, metalness: 0.2 });
                    mesh = new THREE.Mesh(palletGeo, palletMat);
                }
                mesh.castShadow = true;
                mesh.receiveShadow = true;
            } else if (isNext) {
                var hGeo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                var hMat = new THREE.MeshStandardMaterial({
                    color: HIGHLIGHT_COLOR, roughness: 0.3, metalness: 0.1,
                    emissive: new THREE.Color(HIGHLIGHT_COLOR), emissiveIntensity: 0.15,
                    transparent: true, opacity: 0.7, depthWrite: false
                });
                mesh = new THREE.Mesh(hGeo, hMat);
                mesh.castShadow = true;
                mesh.userData.isHighlight = true;
                mesh.renderOrder = 2;
            } else {
                var wGeo = new THREE.BoxGeometry(PALLET_W - 0.08, PALLET_H, palletDepth);
                var wMat = new THREE.MeshBasicMaterial({
                    color: EMPTY_COLOR, wireframe: true,
                    transparent: true, opacity: 0.35, depthWrite: false
                });
                mesh = new THREE.Mesh(wGeo, wMat);
                mesh.renderOrder = 1;
            }

            mesh.position.set(x, y, z);
            mesh.userData.slotIndex = slotIndex;
            slotMeshes.push(mesh);
            scene.add(mesh);
        }
    }

    // ========================================
    // Pallet Drop Animation
    // ========================================

    function animatePalletDrop(slotIndex, callback) {
        var mesh = null;
        slotMeshes.forEach(function (m) {
            if (m.userData.slotIndex === slotIndex) mesh = m;
        });
        if (!mesh) { if (callback) callback(); return; }

        var targetY = mesh.position.y;
        mesh.position.y = targetY + 2;

        mesh.material.color.setHex(PALLET_COLOR);
        mesh.material.emissive = new THREE.Color(0x000000);
        mesh.material.emissiveIntensity = 0;
        mesh.material.opacity = 1;
        mesh.material.transparent = false;
        mesh.material.wireframe = false;
        mesh.material.depthWrite = true;
        mesh.userData.isHighlight = false;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.renderOrder = 0;

        var startY = mesh.position.y;
        var startTime = performance.now();
        var duration = 500;

        function drop(now) {
            var elapsed = now - startTime;
            var progress = Math.min(elapsed / duration, 1);
            var t = 1 - Math.pow(1 - progress, 3);
            mesh.position.y = startY + (targetY - startY) * t;
            if (progress < 1) {
                requestAnimationFrame(drop);
            } else {
                mesh.position.y = targetY;
                if (callback) callback();
            }
        }
        requestAnimationFrame(drop);
    }

    // ========================================
    // Cleanup
    // ========================================

    function disposeScene() {
        if (animationId) cancelAnimationFrame(animationId);
        animationId = null;
        if (topdownAnimId) cancelAnimationFrame(topdownAnimId);
        topdownAnimId = null;

        if (renderer) {
            var container = renderer.domElement.parentNode;
            if (container && container._resizeHandler) {
                window.removeEventListener('resize', container._resizeHandler);
            }
            renderer.dispose();
            if (renderer.domElement && renderer.domElement.parentNode) {
                renderer.domElement.parentNode.removeChild(renderer.domElement);
            }
        }
        if (controls) controls.dispose();

        if (scene) {
            scene.traverse(function (obj) {
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) {
                    if (Array.isArray(obj.material)) {
                        obj.material.forEach(function (m) { m.dispose(); });
                    } else {
                        obj.material.dispose();
                    }
                }
            });
        }

        scene = null;
        camera = null;
        renderer = null;
        controls = null;
        shelfGroup = null;
        slotMeshes = [];
        currentShelfId = null;
        currentAllLevels = null;
    }

    // ========================================
    // Public API
    // ========================================

    window.Shelf3D = {
        open: function (shelfId, trackDeliveryId) {
            disposeScene();

            currentShelfId = shelfId;
            currentDeliveryId = trackDeliveryId || null;
            var overlay = document.getElementById('shelfModalOverlay');
            var container = document.getElementById('threeContainer');
            var topdownCanvas = document.getElementById('topdownCanvas');
            var capacityEl = document.getElementById('shelfCapacity');
            var headerEl = document.getElementById('shelfModalHeader');
            var storeBtn = document.getElementById('markStoredBtn');
            var label3d = document.getElementById('shelfLabel3D');

            if (!container) return;

            if (storeBtn) {
                storeBtn.disabled = false;
                storeBtn.textContent = 'Mark as Stored';
                storeBtn.style.display = '';
                storeBtn.onclick = function() { Shelf3D.markStored(); };
                delete storeBtn.dataset.redirectShelf;
            }

            if (overlay) {
                overlay.classList.add('active');
                document.body.style.overflow = 'hidden';
            }

            var parts = shelfId.split('-');
            var sector = parts[0];
            var unit = parts[1];
            var targetShelf = parseInt(parts[2], 10);
            currentTargetShelf = targetShelf;

            if (headerEl) {
                headerEl.innerHTML =
                    '<span class="shelf-tag">Sector ' + sector + '</span>' +
                    '<span class="shelf-tag">Unit ' + unit + '</span>' +
                    '<span class="shelf-tag">Shelf ' + targetShelf + '</span>';
            }

            if (label3d) {
                label3d.textContent = 'Sector ' + sector + ' \u00B7 Unit ' + unit + ' \u00B7 Shelf ' + targetShelf;
            }

            fetch('/api/shelf-info/?shelf_id=' + encodeURIComponent(shelfId))
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.error) {
                        console.error(data.error);
                        return;
                    }

                    // Update shelf geometry from warehouse config
                    updateShelfConfig(data);

                    if (capacityEl) capacityEl.textContent = data.percentage + '% Full';

                    var ring = document.getElementById('capacityRing');
                    if (ring) {
                        var circumference = 2 * Math.PI * 36;
                        ring.style.strokeDasharray = circumference;
                        ring.style.strokeDashoffset = circumference - (data.percentage / 100) * circumference;
                    }

                    var percentText = document.getElementById('capacityPercent');
                    if (percentText) percentText.textContent = data.percentage + '%';

                    // Track delivery ID from the shelf info
                    if (data.pending_delivery_id) {
                        currentDeliveryId = data.pending_delivery_id;
                    }

                    if (storeBtn) {
                        var progressText = '';
                        if (data.pallets_needed > 0) {
                            progressText = ' (' + data.pallets_stored + '/' + data.pallets_needed + ')';
                        }

                        if (data.pallets_needed > 0 && data.pallets_stored >= data.pallets_needed) {
                            // All pallets already stored — show done state
                            storeBtn.style.display = '';
                            storeBtn.disabled = true;
                            storeBtn.textContent = 'All Pallets Stored' + progressText;
                        } else if (data.next_available !== null) {
                            storeBtn.style.display = '';
                            storeBtn.disabled = false;
                            storeBtn.textContent = 'Mark as Stored' + progressText;
                            storeBtn.dataset.slotIndex = data.next_available;
                        } else if (data.has_pending_delivery && data.next_available_shelf) {
                            // Shelf full but has pending delivery — redirect to next shelf
                            var delivId = currentDeliveryId;
                            storeBtn.style.display = '';
                            storeBtn.disabled = false;
                            storeBtn.textContent = 'Continue to ' + data.next_available_shelf + progressText;
                            storeBtn.dataset.redirectShelf = data.next_available_shelf;
                            storeBtn.onclick = function() { Shelf3D.open(data.next_available_shelf, delivId); };
                        } else {
                            storeBtn.style.display = 'none';
                        }
                    }

                    currentAllLevels = data.all_levels || null;

                    initScene(container);
                    buildShelf(targetShelf);
                    placePallets(data.occupied_slots, data.next_available, targetShelf, data.recently_stored);
                    placeOtherLevelPallets(currentAllLevels, targetShelf);
                    animate();

                    if (topdownCanvas) {
                        topdownPulseTime = 0;
                        animateTopDown(topdownCanvas, data.occupied_slots, data.next_available, targetShelf, sector, unit, data.recently_stored);
                    }
                })
                .catch(function (err) {
                    console.error('Failed to load shelf info:', err);
                });
        },

        close: function () {
            var overlay = document.getElementById('shelfModalOverlay');
            if (overlay) {
                overlay.classList.remove('active');
                document.body.style.overflow = '';
            }
            disposeScene();
        },

        markStored: function () {
            if (!currentShelfId) return;
            var storeBtn = document.getElementById('markStoredBtn');
            var slotIndex = storeBtn ? parseInt(storeBtn.dataset.slotIndex, 10) : null;
            if (slotIndex === null || isNaN(slotIndex)) return;
            if (storeBtn && storeBtn.disabled) return;

            var csrfToken = '';
            var csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (csrfInput) csrfToken = csrfInput.value;
            if (!csrfToken) {
                var csrfCookie = document.cookie.split(';').find(function (c) {
                    return c.trim().startsWith('csrftoken=');
                });
                if (csrfCookie) csrfToken = csrfCookie.split('=')[1];
            }

            if (storeBtn) {
                storeBtn.disabled = true;
                storeBtn.textContent = 'Storing...';
            }

            var payload = { shelf_id: currentShelfId, slot_index: slotIndex };
            if (currentDeliveryId) payload.delivery_id = currentDeliveryId;

            fetch('/api/mark-stored/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify(payload)
            })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.error) {
                    console.error(data.error);
                    if (storeBtn) {
                        storeBtn.textContent = data.error;
                        storeBtn.disabled = true;
                    }
                    return;
                }

                animatePalletDrop(slotIndex, function () {
                    var capacityEl = document.getElementById('shelfCapacity');
                    if (capacityEl) capacityEl.textContent = data.percentage + '% Full';

                    var ring = document.getElementById('capacityRing');
                    if (ring) {
                        var circumference = 2 * Math.PI * 36;
                        ring.style.strokeDashoffset = circumference - (data.percentage / 100) * circumference;
                    }

                    var percentText = document.getElementById('capacityPercent');
                    if (percentText) percentText.textContent = data.percentage + '%';

                    // Rebuild all slot meshes to reflect new state
                    rebuildSlots(data.occupied_slots, data.next_available, currentTargetShelf, slotIndex);

                    // Re-render other level pallets (update currentAllLevels for this level)
                    removeOtherLevelPallets();
                    if (currentAllLevels) {
                        currentAllLevels[String(currentTargetShelf)] = {
                            shelf_id: currentShelfId,
                            occupied_slots: data.occupied_slots,
                            recently_stored: [slotIndex],
                            percentage: data.percentage,
                            next_available: data.next_available
                        };
                        placeOtherLevelPallets(currentAllLevels, currentTargetShelf);
                    }

                    var topdownCanvas = document.getElementById('topdownCanvas');
                    if (topdownCanvas) {
                        if (topdownAnimId) cancelAnimationFrame(topdownAnimId);
                        var parts = currentShelfId.split('-');
                        animateTopDown(topdownCanvas, data.occupied_slots, data.next_available, currentTargetShelf, parts[0], parts[1], [slotIndex]);
                    }

                    // Check quantity-based capacity: disable if all pallets for this delivery are placed
                    var allPalletsPlaced = data.pallets_needed > 0 && data.pallets_stored >= data.pallets_needed;

                    if (storeBtn) {
                        if (allPalletsPlaced) {
                            storeBtn.textContent = 'All Pallets Stored (' + data.pallets_stored + '/' + data.pallets_needed + ')';
                            storeBtn.disabled = true;
                        } else if (data.overflow_shelf) {
                            // Shelf is full but delivery has remaining pallets — switch to overflow shelf
                            storeBtn.disabled = false;
                            var progressText = ' (' + data.pallets_stored + '/' + data.pallets_needed + ')';
                            storeBtn.textContent = 'Continue on ' + data.overflow_shelf + progressText;
                            storeBtn.dataset.slotIndex = data.overflow_next_slot;
                            // Auto-switch to the new shelf after a short delay, passing delivery ID
                            var delivId = currentDeliveryId;
                            setTimeout(function() {
                                Shelf3D.open(data.overflow_shelf, delivId);
                            }, 1500);
                        } else if (data.next_available !== null) {
                            storeBtn.disabled = false;
                            var progressText = data.pallets_needed > 0
                                ? ' (' + data.pallets_stored + '/' + data.pallets_needed + ')'
                                : '';
                            storeBtn.textContent = 'Mark as Stored' + progressText;
                            storeBtn.dataset.slotIndex = data.next_available;
                        } else {
                            storeBtn.textContent = 'Shelf Full';
                            storeBtn.disabled = true;
                        }
                    }

                    // Update row statuses — support both legacy and operator table layouts
                    var rows = document.querySelectorAll('tr[data-shelf="' + currentShelfId + '"]');
                    // Also find rows by delivery ID (operator delivery table)
                    if (currentDeliveryId) {
                        var deliveryRows = document.querySelectorAll('tr[data-delivery-id="' + currentDeliveryId + '"]');
                        deliveryRows.forEach(function(r) {
                            var found = false;
                            rows.forEach(function(existing) { if (existing === r) found = true; });
                            if (!found) {
                                rows = Array.prototype.slice.call(rows);
                                rows.push(r);
                            }
                        });
                    }
                    rows.forEach(function(row) {
                        // Legacy layout: .shipment-status / .shelf-status
                        if (allPalletsPlaced) {
                            var shipmentBadge = row.querySelector('.shipment-status');
                            if (shipmentBadge) {
                                shipmentBadge.textContent = 'Placed';
                                shipmentBadge.className = 'status-badge shipment-status placed';
                            }
                        }
                        var shelfBadge = row.querySelector('.shelf-status');
                        if (shelfBadge) {
                            if (data.percentage >= 100) {
                                shelfBadge.textContent = 'Full (' + data.occupied_count + '/4)';
                                shelfBadge.className = 'status-badge shelf-status shelf-full-badge';
                            } else {
                                shelfBadge.textContent = 'Open (' + data.occupied_count + '/4)';
                                shelfBadge.className = 'status-badge shelf-status shelf-open-badge';
                            }
                        }

                        // Operator layout: .op-status-badge and progress span
                        if (allPalletsPlaced) {
                            var opBadge = row.querySelector('.op-status-badge');
                            if (opBadge) {
                                opBadge.textContent = 'STORED';
                                opBadge.className = 'op-status-badge op-status-stored';
                            }
                            // Update progress column
                            var progressCells = row.querySelectorAll('.op-td-mono');
                            progressCells.forEach(function(cell) {
                                if (cell.textContent.match(/\d+\/\d+/)) {
                                    cell.textContent = 'done';
                                    cell.className = 'op-td-mono op-progress-full';
                                }
                            });
                            // Hide store button
                            var storeActionBtn = row.querySelector('.op-btn-store');
                            if (storeActionBtn) {
                                storeActionBtn.style.display = 'none';
                            }
                        } else {
                            // Update progress count
                            var progressCells = row.querySelectorAll('.op-td-mono');
                            progressCells.forEach(function(cell) {
                                if (cell.textContent.match(/\d+\/\d+/)) {
                                    cell.textContent = data.pallets_stored + '/' + data.pallets_needed;
                                    cell.className = 'op-td-mono ' + (data.pallets_stored > 0 ? 'op-progress-partial' : 'op-progress-none');
                                }
                            });
                        }
                    });

                    // If overflow happened, also update the shelf_id cell in the table row
                    if (data.overflow_shelf) {
                        rows.forEach(function(row) {
                            row.dataset.shelf = data.overflow_shelf;
                            // Find the shelf ID cell and update it
                            var tds = row.querySelectorAll('td');
                            for (var i = 0; i < tds.length; i++) {
                                if (tds[i].textContent.trim() === currentShelfId) {
                                    tds[i].textContent = data.overflow_shelf;
                                    break;
                                }
                            }
                        });
                    }
                });
            })
            .catch(function (err) {
                console.error('Failed to mark stored:', err);
                if (storeBtn) {
                    storeBtn.disabled = false;
                    storeBtn.textContent = 'Mark as Stored';
                }
            });
        },

        // ── Manufacturing Order Storage Mode ──
        openForMO: function (shelfId, orderId, warehouseId, onStoredCallback) {
            disposeScene();

            currentShelfId = shelfId;
            currentDeliveryId = null;
            currentMOId = orderId;
            currentMOWarehouseId = warehouseId;

            var overlay = document.getElementById('shelfModalOverlay');
            var container = document.getElementById('threeContainer');
            var topdownCanvas = document.getElementById('topdownCanvas');
            var capacityEl = document.getElementById('shelfCapacity');
            var headerEl = document.getElementById('shelfModalHeader');
            var storeBtn = document.getElementById('markStoredBtn');
            var label3d = document.getElementById('shelfLabel3D');

            if (!container) return;

            if (storeBtn) {
                storeBtn.disabled = false;
                storeBtn.textContent = 'Store Finished Order';
                storeBtn.style.display = '';
                storeBtn.onclick = function () { Shelf3D.storeFinishedOrder(onStoredCallback); };
                delete storeBtn.dataset.redirectShelf;
            }

            if (overlay) {
                overlay.classList.add('active');
                document.body.style.overflow = 'hidden';
            }

            var parts = shelfId.split('-');
            var sector = parts[0];
            var unit = parts[1];
            var targetShelf = parseInt(parts[2], 10);
            currentTargetShelf = targetShelf;

            if (headerEl) {
                headerEl.innerHTML =
                    '<span class="shelf-tag">Sector ' + sector + '</span>' +
                    '<span class="shelf-tag">Unit ' + unit + '</span>' +
                    '<span class="shelf-tag">Shelf ' + targetShelf + '</span>';
            }

            if (label3d) {
                label3d.textContent = 'Sector ' + sector + ' \u00B7 Unit ' + unit + ' \u00B7 Shelf ' + targetShelf;
            }

            var shelfUrl = '/api/shelf-info/?shelf_id=' + encodeURIComponent(shelfId);
            if (warehouseId) shelfUrl += '&warehouse_id=' + warehouseId;

            fetch(shelfUrl)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.error) {
                        console.error(data.error);
                        return;
                    }

                    updateShelfConfig(data);

                    if (capacityEl) capacityEl.textContent = data.percentage + '% Full';

                    var ring = document.getElementById('capacityRing');
                    if (ring) {
                        var circumference = 2 * Math.PI * 36;
                        ring.style.strokeDasharray = circumference;
                        ring.style.strokeDashoffset = circumference - (data.percentage / 100) * circumference;
                    }

                    var percentText = document.getElementById('capacityPercent');
                    if (percentText) percentText.textContent = data.percentage + '%';

                    if (storeBtn) {
                        if (data.next_available !== null) {
                            storeBtn.style.display = '';
                            storeBtn.disabled = false;
                            storeBtn.textContent = 'Store Finished Order';
                            storeBtn.dataset.slotIndex = data.next_available;
                        } else {
                            storeBtn.textContent = 'Shelf Full';
                            storeBtn.disabled = true;
                        }
                    }

                    currentAllLevels = data.all_levels || null;

                    initScene(container);
                    buildShelf(targetShelf);
                    placePallets(data.occupied_slots, data.next_available, targetShelf, data.recently_stored);
                    placeOtherLevelPallets(currentAllLevels, targetShelf);
                    animate();

                    if (topdownCanvas) {
                        topdownPulseTime = 0;
                        animateTopDown(topdownCanvas, data.occupied_slots, data.next_available, targetShelf, sector, unit, data.recently_stored);
                    }
                })
                .catch(function (err) {
                    console.error('Failed to load shelf info:', err);
                });
        },

        storeFinishedOrder: function (onStoredCallback) {
            if (!currentShelfId || !currentMOId) return;
            var storeBtn = document.getElementById('markStoredBtn');
            var slotIndex = storeBtn ? parseInt(storeBtn.dataset.slotIndex, 10) : null;
            if (slotIndex === null || isNaN(slotIndex)) return;
            if (storeBtn && storeBtn.disabled) return;

            var csrfToken = '';
            var csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            if (csrfInput) csrfToken = csrfInput.value;
            if (!csrfToken) {
                var csrfCookie = document.cookie.split(';').find(function (c) {
                    return c.trim().startsWith('csrftoken=');
                });
                if (csrfCookie) csrfToken = csrfCookie.split('=')[1];
            }

            if (storeBtn) {
                storeBtn.disabled = true;
                storeBtn.textContent = 'Storing...';
            }

            fetch('/api/store-finished-order/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify({
                    order_id: currentMOId,
                    warehouse_id: currentMOWarehouseId,
                    shelf_id: currentShelfId,
                    slot_index: slotIndex
                })
            })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data.error) {
                    console.error(data.error);
                    if (storeBtn) {
                        storeBtn.textContent = data.error;
                        storeBtn.disabled = true;
                    }
                    return;
                }

                animatePalletDrop(slotIndex, function () {
                    if (storeBtn) {
                        storeBtn.textContent = 'Stored \u2714';
                        storeBtn.disabled = true;
                    }

                    // Rebuild slots to show the newly placed pallet
                    var refreshUrl = '/api/shelf-info/?shelf_id=' + encodeURIComponent(currentShelfId);
                    if (currentMOWarehouseId) refreshUrl += '&warehouse_id=' + currentMOWarehouseId;
                    fetch(refreshUrl)
                        .then(function (r) { return r.json(); })
                        .then(function (info) {
                            if (!info.error) {
                                var capacityEl = document.getElementById('shelfCapacity');
                                if (capacityEl) capacityEl.textContent = info.percentage + '% Full';

                                var ring = document.getElementById('capacityRing');
                                if (ring) {
                                    var circumference = 2 * Math.PI * 36;
                                    ring.style.strokeDashoffset = circumference - (info.percentage / 100) * circumference;
                                }

                                var percentText = document.getElementById('capacityPercent');
                                if (percentText) percentText.textContent = info.percentage + '%';

                                rebuildSlots(info.occupied_slots, info.next_available, currentTargetShelf, slotIndex);

                                removeOtherLevelPallets();
                                if (currentAllLevels) {
                                    currentAllLevels[String(currentTargetShelf)] = {
                                        shelf_id: currentShelfId,
                                        occupied_slots: info.occupied_slots,
                                        recently_stored: [slotIndex],
                                        percentage: info.percentage,
                                        next_available: info.next_available
                                    };
                                    placeOtherLevelPallets(currentAllLevels, currentTargetShelf);
                                }

                                var topdownCanvas = document.getElementById('topdownCanvas');
                                if (topdownCanvas) {
                                    if (topdownAnimId) cancelAnimationFrame(topdownAnimId);
                                    var parts = currentShelfId.split('-');
                                    animateTopDown(topdownCanvas, info.occupied_slots, info.next_available, currentTargetShelf, parts[0], parts[1], [slotIndex]);
                                }
                            }
                        });

                    // Fire callback for real-time table updates
                    if (typeof onStoredCallback === 'function') {
                        onStoredCallback(data);
                    }
                });
            })
            .catch(function (err) {
                console.error('Failed to store finished order:', err);
                if (storeBtn) {
                    storeBtn.disabled = false;
                    storeBtn.textContent = 'Store Finished Order';
                }
            });
        }
    };
})();
