/* Keyboard access for click targets that aren't buttons or links.
 *
 * Several pages use <div onclick="..."> for menu items, cards and tabs. A mouse can use them,
 * a keyboard or screen reader can't: they aren't in the Tab order and don't announce as
 * controls. This makes every such element (including ones added later by page scripts) reachable
 * with Tab, announced as a button (or a link when it navigates), and activated with Enter or
 * Space. Real <button>/<a> elements are still the better choice for new markup.
 */
(function () {
    'use strict';

    var NATIVE = /^(A|BUTTON|INPUT|SELECT|TEXTAREA|LABEL|SUMMARY|OPTION)$/;
    var SKIP_CLASS = /(^|\s)(modal-overlay|sidebar-overlay|overlay|backdrop)(\s|$)/;

    function needsHelp(el) {
        if (NATIVE.test(el.tagName) || el.hasAttribute('data-a11y-done')) return false;
        var handler = el.getAttribute('onclick') || '';
        if (!handler || /^\s*event\.stopPropagation\(\)\s*;?\s*$/.test(handler)) return false;
        if (SKIP_CLASS.test(el.className || '')) return false;
        return true;
    }

    function enhance(el) {
        if (!needsHelp(el)) return;
        el.setAttribute('data-a11y-done', '');
        if (!el.hasAttribute('role')) {
            var navigates = /location\.href|window\.open/.test(el.getAttribute('onclick'));
            el.setAttribute('role', navigates ? 'link' : 'button');
        }
        if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
        el.addEventListener('keydown', function (e) {
            if (e.target !== el) return;
            if (e.key === 'Enter' || (e.key === ' ' && el.getAttribute('role') !== 'link')) {
                e.preventDefault();
                el.click();
            }
        });
    }

    function scan(root) {
        if (!root || root.nodeType !== 1) return;
        if (root.hasAttribute('onclick')) enhance(root);
        var list = root.querySelectorAll('[onclick]');
        for (var i = 0; i < list.length; i++) enhance(list[i]);
    }

    function start() {
        scan(document.body);
        if (typeof MutationObserver === 'function') {
            new MutationObserver(function (records) {
                for (var i = 0; i < records.length; i++) {
                    var added = records[i].addedNodes;
                    for (var j = 0; j < added.length; j++) scan(added[j]);
                }
            }).observe(document.body, { childList: true, subtree: true });
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
