document.addEventListener('DOMContentLoaded', function () {
    // Animated counters
    var counters = document.querySelectorAll('[data-count]');
    var duration = 700;

    function animateCounter(el) {
        var target = parseInt(el.dataset.count, 10);
        if (isNaN(target)) return;
        var start = performance.now();

        function update(now) {
            var elapsed = now - start;
            var progress = Math.min(elapsed / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.floor(eased * target).toLocaleString('en-IN');
            if (progress < 1) {
                requestAnimationFrame(update);
            } else {
                el.textContent = target.toLocaleString('en-IN');
            }
        }

        requestAnimationFrame(update);
    }

    if ('IntersectionObserver' in window) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    animateCounter(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.3 });

        counters.forEach(function (el) {
            el.textContent = '0';
            observer.observe(el);
        });
    } else {
        counters.forEach(animateCounter);
    }

    // Shipment dock — N key shortcut
    document.addEventListener('keydown', function (e) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.key === 'n' || e.key === 'N') {
            if (typeof triggerNewShipment === 'function') {
                triggerNewShipment();
            }
        }
    });

    // Table search filtering
    var searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function () {
            var query = this.value.toLowerCase();
            var rows = document.querySelectorAll('.data-table tbody tr');
            rows.forEach(function (row) {
                var text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? '' : 'none';
            });
        });
    }
});
