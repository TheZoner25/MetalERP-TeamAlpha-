/**
 * Operator layout mode toggle logic.
 * Handles switching between AI Agent (full-screen chat) and UI Mode (70/30 split).
 */
(function() {
    'use strict';

    const layout = document.getElementById('operatorLayout');
    const toggleContainer = document.getElementById('modeToggle');
    if (!layout || !toggleContainer) return;

    const agentBtn = toggleContainer.querySelector('[data-mode="agent"]');
    const uiBtn = toggleContainer.querySelector('[data-mode="ui"]');

    function setMode(mode) {
        if (mode === 'ui') {
            layout.classList.remove('mode-agent');
            layout.classList.add('mode-ui');
            agentBtn.classList.remove('active');
            uiBtn.classList.add('active');
        } else {
            layout.classList.remove('mode-ui');
            layout.classList.add('mode-agent');
            uiBtn.classList.remove('active');
            agentBtn.classList.add('active');
        }
        localStorage.setItem('operatorMode', mode);
    }

    agentBtn.addEventListener('click', function() { setMode('agent'); });
    uiBtn.addEventListener('click', function() { setMode('ui'); });

    // Restore saved mode preference
    var saved = localStorage.getItem('operatorMode');

    // If we are on a UI sub-page (has ui_content), default to UI mode
    var hasUIContent = layout.classList.contains('mode-ui');
    if (hasUIContent && !saved) {
        setMode('ui');
    } else if (saved) {
        setMode(saved);
        // If saved is agent but page has UI content, still allow it
    }
})();
