/*
 * Native features for the DevOps Agent iPhone app (mobile/, Capacitor).
 *
 * Loaded only when the server sees the app's user agent (templates check `ios_app`), and
 * every feature checks for the native bridge first, so in a browser this file does nothing.
 *
 *  1. Push notifications: ask once, register the APNs token with /api/push/devices, open the
 *     approval page when a notification is tapped, unregister on Log out.
 *  2. Face ID before running a risky action: confirming or approving a request first asks
 *     for Face ID (or the passcode). Cancelling a request is never gated.
 *  3. Share: a Share button next to Copy on the agent's replies.
 *
 * Native plugins are reached through window.Capacitor.registerPlugin(name), the bridge's
 * no-bundler API; the names match the native plugin ids in mobile/node_modules.
 */
(function () {
    'use strict';

    var Cap = window.Capacitor;
    if (!Cap || typeof Cap.isNativePlatform !== 'function' || !Cap.isNativePlatform()) return;

    function plugin(name) {
        try { return Cap.registerPlugin(name); } catch (e) { return null; }
    }
    function store(key, value) {
        try {
            if (value === undefined) return window.localStorage.getItem(key);
            if (value === null) window.localStorage.removeItem(key);
            else window.localStorage.setItem(key, value);
        } catch (e) { /* storage can be unavailable; features still work for this page */ }
        return null;
    }

    var Push = plugin('PushNotifications');
    var Biometric = plugin('BiometricAuthNative');
    var Share = plugin('Share');
    var TOKEN_KEY = 'devopsagent.pushToken';

    // ---- 1. Push notifications ------------------------------------------------------------
    var signedIn = document.body && document.body.dataset.signedIn === '1';

    function sendToken(token) {
        return fetch('/api/push/devices', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({token: token, environment: 'production'}),
        }).then(function (r) { if (r.ok) store(TOKEN_KEY, token); });
    }

    function safeLink(link) {
        return typeof link === 'string' && link.charAt(0) === '/' && link.charAt(1) !== '/' ? link : null;
    }

    if (Push) {
        Push.addListener('registration', function (t) {
            // iOS hands the token over on every launch; send it only when it's new for this login.
            if (t && t.value && t.value !== store(TOKEN_KEY)) sendToken(t.value);
        });
        Push.addListener('registrationError', function () { /* user can still use the app */ });
        Push.addListener('pushNotificationActionPerformed', function (action) {
            var data = (action && action.notification && action.notification.data) || {};
            var link = safeLink(data.link);
            if (link && window.location.pathname !== link) window.location.href = link;
        });

        if (signedIn) {
            Push.checkPermissions().then(function (p) {
                if (p.receive === 'granted') return Push.register();
                if (p.receive === 'prompt' || p.receive === 'prompt-with-rationale') {
                    return Push.requestPermissions().then(function (r) {
                        if (r.receive === 'granted') return Push.register();
                    });
                }
            }).catch(function () {});
        }
    }

    document.addEventListener('click', function (ev) {
        var el = ev.target && ev.target.closest && ev.target.closest('a[href="/logout"], [data-logout]');
        var token = store(TOKEN_KEY);
        if (!el || !token) return;
        ev.preventDefault();
        ev.stopPropagation();
        fetch('/api/push/devices', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({token: token}),
        }).catch(function () {}).then(function () {
            store(TOKEN_KEY, null);
            window.location.href = '/logout';
        });
    }, true);

    // ---- 2. Face ID before running a risky action -----------------------------------------
    var RUNS_ACTION = /^\/api\/(approvals|changes)\/\d+\/(confirm|approve)\/?$/;

    function pathOf(input) {
        try { return new URL(typeof input === 'string' ? input : input.url, window.location.href).pathname; }
        catch (e) { return ''; }
    }

    function faceIdOk() {
        if (!Biometric) return Promise.resolve(true);
        return Biometric.checkBiometry().then(function (b) {
            if (!b.isAvailable && !b.deviceIsSecure) return true; // no Face ID or passcode set up
            return Biometric.internalAuthenticate({
                reason: 'Confirm this action on your cloud account',
                cancelTitle: 'Cancel',
                allowDeviceCredential: true,
            }).then(function () { return true; }, function () { return false; });
        }, function () { return true; });
    }

    var realFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
        var method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (method !== 'POST' || !RUNS_ACTION.test(pathOf(input))) return realFetch(input, init);
        return faceIdOk().then(function (ok) {
            if (ok) return realFetch(input, init);
            return new Response(JSON.stringify({success: false, error: 'Face ID was cancelled, so nothing ran.'}),
                {status: 403, headers: {'Content-Type': 'application/json'}});
        });
    };

    // ---- 3. Share the agent's replies -----------------------------------------------------
    function addShareButton(row) {
        if (!Share || row.querySelector('.share-btn')) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'copy-btn share-btn';
        btn.textContent = 'Share';
        btn.addEventListener('click', function () {
            var holder = row.parentElement;
            if (!holder) return;
            var clone = holder.cloneNode(true);
            clone.querySelectorAll('.message-actions').forEach(function (n) { n.remove(); });
            var text = (clone.innerText || clone.textContent || '').trim();
            if (text) Share.share({title: 'DevOps Agent', text: text}).catch(function () {});
        });
        row.appendChild(btn);
    }

    function scan(root) {
        if (!root || !root.querySelectorAll) return;
        if (root.classList && root.classList.contains('message-actions')) addShareButton(root);
        root.querySelectorAll('.message-actions').forEach(addShareButton);
    }

    scan(document);
    new MutationObserver(function (records) {
        records.forEach(function (r) { r.addedNodes.forEach(scan); });
    }).observe(document.documentElement, {childList: true, subtree: true});
})();
