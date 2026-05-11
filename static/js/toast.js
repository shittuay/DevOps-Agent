/**
 * Global Toast Notification System
 * Usage: showToast('Message text', 'success|error|info|warning')
 */
(function() {
    'use strict';

    const ICONS = {
        success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
        error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
        warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
    };

    function getContainer() {
        var existing = document.getElementById('global-toast-container');
        if (existing) return existing;
        var container = document.createElement('div');
        container.id = 'global-toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
        return container;
    }

    function showToast(message, type) {
        type = type || 'info';
        var container = getContainer();
        var toast = document.createElement('div');
        toast.className = 'toast ' + type;
        var icon = document.createElement('span');
        icon.className = 'toast-icon';
        icon.innerHTML = ICONS[type] || ICONS.info;
        var text = document.createElement('span');
        text.className = 'toast-message';
        // Use textContent so caller-supplied text is never parsed as HTML
        var safeMsg = typeof message === 'string' ? message : String(message);
        // Truncate very long messages (e.g. HTML error bodies) to 200 chars
        text.textContent = safeMsg.length > 200 ? safeMsg.slice(0, 197) + '…' : safeMsg;
        toast.appendChild(icon);
        toast.appendChild(text);

        toast.addEventListener('click', function() {
            toast.classList.remove('show');
            setTimeout(function() { toast.remove(); }, 350);
        });

        container.appendChild(toast);
        requestAnimationFrame(function() {
            requestAnimationFrame(function() {
                toast.classList.add('show');
            });
        });

        setTimeout(function() {
            if (toast.parentNode) {
                toast.classList.remove('show');
                setTimeout(function() { toast.remove(); }, 350);
            }
        }, 4000);
    }

    window.showToast = showToast;
})();
