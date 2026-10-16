/* DevOps Agent - Theme Toggle System */

// Set theme and update UI
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);

    // Update button states (old pill buttons and the profile-menu Light/Dark choice)
    document.querySelectorAll('.theme-toggle-btn, .theme-choice-btn').forEach(btn => {
        if (btn.getAttribute('data-theme') === theme) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

// Initialize theme on page load
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);
}

// Add a floating theme toggle only to pages that have no other way to switch theme.
// Signed-in pages put Light/Dark in the profile menu ([data-theme-menu]).
function addThemeToggle() {
    if (document.querySelector('.theme-toggle, [data-theme-menu]')) return;

    const toggle = document.createElement('div');
    toggle.className = 'theme-toggle theme-toggle-floating';
    toggle.setAttribute('role', 'group');
    toggle.setAttribute('aria-label', 'Theme');
    toggle.innerHTML = `
        <button class="theme-toggle-btn" data-theme="dark" title="Dark Mode">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
        </button>
        <button class="theme-toggle-btn" data-theme="light" title="Light Mode">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="5"></circle>
                <line x1="12" y1="1" x2="12" y2="3"></line>
                <line x1="12" y1="21" x2="12" y2="23"></line>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                <line x1="1" y1="12" x2="3" y2="12"></line>
                <line x1="21" y1="12" x2="23" y2="12"></line>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
            </svg>
        </button>
    `;
    document.body.appendChild(toggle);
}

// Delegated click handler — works for injected and pre-existing toggles alike
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.theme-toggle-btn, .theme-choice-btn');
    if (btn) setTheme(btn.getAttribute('data-theme'));
});

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    addThemeToggle();
});

// Also run immediately in case DOM is already loaded
if (document.readyState === 'complete' || document.readyState === 'interactive') {
    initTheme();
}
