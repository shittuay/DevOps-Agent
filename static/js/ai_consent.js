/* Asks, once, before the iPhone app sends anything to the AI providers.
 *
 * Apple's App Review Guideline 5.1.2(i): say when personal data goes to a third-party AI and
 * get permission first. Loaded only in the app (templates check `ios_app`). It wraps fetch:
 * the first POST to an AI endpoint shows the screen below; "Allow" saves the answer
 * (/api/ai-consent) and lets the request through, "Not now" returns a 403 the page shows as an
 * error. The server refuses the same requests until the user has allowed it
 * (services/ai_consent.py), so this screen is the explanation, not the enforcement.
 * Settings > Profile has a box (#aiConsentBox) to withdraw or allow it again.
 */
(function () {
    'use strict';

    var AI_PATH = /^\/(api\/chat(\/stream)?|curriculum\/api\/(ai-guide|quiz\/generate))\/?$/;
    // Keep in step with AI_PROVIDERS in services/ai_consent.py.
    var PROVIDERS = [
        ['Anthropic', 'checks every message for abuse, and answers on plans that use Claude'],
        ['Moonshot AI', 'answers on plans that use Kimi'],
        ['Groq', 'answers only when the main model is unavailable']
    ];
    var DECLINED = "Your message wasn't sent. DevOps Agent needs your permission to share it with " +
        'its AI providers. Send it again to choose, or allow it in Settings > Profile.';

    var body = document.body;
    if (!body || body.getAttribute('data-signed-in') !== '1' || typeof window.fetch !== 'function') return;

    var allowed = body.getAttribute('data-ai-consent') === '1';
    var originalFetch = window.fetch.bind(window);
    var pending = null;

    function setAllowed(value) {
        allowed = value;
        body.setAttribute('data-ai-consent', value ? '1' : '0');
        renderSettingsBox();
    }

    function saveAnswer(method) {
        return originalFetch('/api/ai-consent', {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
            credentials: 'same-origin'
        }).then(function (resp) {
            if (!resp.ok) throw new Error('status ' + resp.status);
            return resp.json();
        }).then(function (state) {
            setAllowed(!!state.allowed);
            return state;
        });
    }

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text) node.textContent = text;
        return node;
    }

    function injectStyles() {
        if (document.getElementById('aiConsentStyles')) return;
        var css =
            '.aic-backdrop{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.6);display:flex;' +
            'align-items:flex-end;justify-content:center;padding:16px;padding-bottom:max(16px,env(safe-area-inset-bottom));}' +
            '@media (min-width:600px){.aic-backdrop{align-items:center;}}' +
            '.aic-sheet{width:100%;max-width:460px;max-height:calc(100dvh - 32px);overflow-y:auto;box-sizing:border-box;' +
            'background:var(--bg-secondary,#16161d);color:var(--text-primary,#f2f2f2);border:1px solid var(--border-subtle,#2c2c36);' +
            'border-radius:18px;padding:24px 22px 20px;font-family:Outfit,-apple-system,sans-serif;box-shadow:0 20px 60px rgba(0,0,0,.45);}' +
            '.aic-sheet h2{font-family:Syne,Outfit,sans-serif;font-weight:800;font-size:22px;margin:0 0 10px;}' +
            '.aic-sheet p,.aic-sheet li{font-size:15px;line-height:1.55;color:var(--text-secondary,#b8b8c2);margin:0 0 10px;overflow-wrap:anywhere;}' +
            '.aic-sheet ul{margin:0 0 12px 20px;padding:0;}' +
            '.aic-sheet li{margin-bottom:4px;}' +
            '.aic-sheet strong{color:var(--text-primary,#f2f2f2);}' +
            '.aic-sheet a{color:var(--accent-primary,#ff6b35);}' +
            '.aic-label{font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--text-tertiary,#8a8a96);margin:14px 0 6px;}' +
            '.aic-error{color:#ff6b6b;font-size:14px;margin:6px 0 0;display:none;}' +
            '.aic-actions{display:flex;flex-direction:column;gap:10px;margin-top:18px;}' +
            '.aic-actions button{font:inherit;font-size:16px;font-weight:600;border-radius:12px;padding:13px 16px;cursor:pointer;min-height:48px;}' +
            '.aic-allow{background:var(--accent-primary,#ff6b35);color:#fff;border:none;}' +
            '.aic-allow[disabled]{opacity:.6;}' +
            '.aic-later{background:transparent;color:var(--text-primary,#f2f2f2);border:1px solid var(--border-subtle,#2c2c36);}';
        var style = el('style', { id: 'aiConsentStyles' });
        style.textContent = css;
        document.head.appendChild(style);
    }

    function ask() {
        if (pending) return pending;
        pending = new Promise(function (resolve) {
            injectStyles();
            var previousFocus = document.activeElement;
            var backdrop = el('div', { 'class': 'aic-backdrop', id: 'aiConsentDialog' });
            var sheet = el('div', {
                'class': 'aic-sheet', role: 'dialog', 'aria-modal': 'true',
                'aria-labelledby': 'aicTitle', 'aria-describedby': 'aicIntro'
            });
            sheet.appendChild(el('h2', { id: 'aicTitle' }, 'Before you chat'));
            sheet.appendChild(el('p', { id: 'aicIntro' },
                'To answer you, DevOps Agent sends your messages to AI services run by other companies.'));

            sheet.appendChild(el('div', { 'class': 'aic-label' }, 'What is sent'));
            var what = el('ul');
            ['What you type and attach',
             'Results of actions the agent runs for you, which can include names, IDs, settings and costs of your cloud resources',
             'Earlier messages in the same conversation, so it can follow along'
            ].forEach(function (t) { what.appendChild(el('li', null, t)); });
            sheet.appendChild(what);

            sheet.appendChild(el('div', { 'class': 'aic-label' }, 'Who receives it'));
            var who = el('ul');
            PROVIDERS.forEach(function (p) {
                var li = el('li');
                li.appendChild(el('strong', null, p[0]));
                li.appendChild(document.createTextNode(': ' + p[1]));
                who.appendChild(li);
            });
            sheet.appendChild(who);

            var more = el('p');
            more.appendChild(document.createTextNode('They use it to produce answers. We don’t sell your data or use it for ads. See our '));
            more.appendChild(el('a', { href: '/privacy-policy' }, 'privacy policy'));
            more.appendChild(document.createTextNode('. You can withdraw this at any time in Settings › Profile.'));
            sheet.appendChild(more);

            var error = el('p', { 'class': 'aic-error', role: 'alert' });
            sheet.appendChild(error);

            var actions = el('div', { 'class': 'aic-actions' });
            var allowBtn = el('button', { type: 'button', 'class': 'aic-allow' }, 'Allow');
            var laterBtn = el('button', { type: 'button', 'class': 'aic-later' }, 'Not now');
            actions.appendChild(allowBtn);
            actions.appendChild(laterBtn);
            sheet.appendChild(actions);
            backdrop.appendChild(sheet);
            document.body.appendChild(backdrop);

            function finish(answer) {
                document.removeEventListener('keydown', onKey, true);
                if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
                pending = null;
                if (previousFocus && previousFocus.focus) { try { previousFocus.focus(); } catch (_) {} }
                resolve(answer);
            }
            function onKey(e) {
                if (e.key === 'Escape') { e.preventDefault(); finish(false); }
            }
            document.addEventListener('keydown', onKey, true);

            allowBtn.addEventListener('click', function () {
                allowBtn.disabled = true;
                allowBtn.textContent = 'Saving…';
                error.style.display = 'none';
                saveAnswer('POST').then(function () { finish(true); }).catch(function () {
                    allowBtn.disabled = false;
                    allowBtn.textContent = 'Allow';
                    error.textContent = 'Couldn’t save your answer. Check your connection and try again.';
                    error.style.display = 'block';
                });
            });
            laterBtn.addEventListener('click', function () { finish(false); });
            allowBtn.focus();
        });
        return pending;
    }

    function declined() {
        return new Response(JSON.stringify({ error: DECLINED, code: 'ai_consent_declined' }), {
            status: 403, headers: { 'Content-Type': 'application/json' }
        });
    }

    window.fetch = function (input, init) {
        if (allowed) return originalFetch(input, init);
        var url, method;
        try {
            url = new URL(typeof input === 'string' ? input : (input && input.url) || '', window.location.href);
            method = ((init && init.method) || (input && typeof input !== 'string' && input.method) || 'GET').toUpperCase();
        } catch (_) {
            return originalFetch(input, init);
        }
        if (method !== 'POST' || url.origin !== window.location.origin || !AI_PATH.test(url.pathname)) {
            return originalFetch(input, init);
        }
        return ask().then(function (yes) { return yes ? originalFetch(input, init) : declined(); });
    };

    // Settings > Profile
    function renderSettingsBox() {
        var box = document.getElementById('aiConsentBox');
        if (!box) return;
        var status = box.querySelector('[data-aic-status]');
        var button = box.querySelector('[data-aic-toggle]');
        if (status) {
            status.textContent = allowed
                ? 'Allowed. Your messages are sent to Anthropic, Moonshot AI and Groq to produce answers.'
                : 'Not allowed. The agent can’t answer until you allow it.';
        }
        if (button) button.textContent = allowed ? 'Withdraw permission' : 'Allow';
    }

    function wireSettingsBox() {
        var box = document.getElementById('aiConsentBox');
        if (!box) return;
        var button = box.querySelector('[data-aic-toggle]');
        var error = box.querySelector('[data-aic-error]');
        renderSettingsBox();
        if (!button) return;
        button.addEventListener('click', function () {
            button.disabled = true;
            if (error) error.style.display = 'none';
            var done = function () { button.disabled = false; };
            if (allowed) {
                saveAnswer('DELETE').then(done).catch(function () {
                    done();
                    if (error) { error.textContent = 'Couldn’t save. Try again.'; error.style.display = 'block'; }
                });
            } else {
                ask().then(done);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireSettingsBox);
    } else {
        wireSettingsBox();
    }
})();
