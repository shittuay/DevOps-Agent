// The user's own pending requests, with Confirm / Cancel. Used by /approvals/mine and,
// for reviewers, the top of /approvals (their own requests never showed there before
// 2026-10-17, so an admin saw an empty Approvals page while requests waited on them).
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
}

async function loadMyRequests(list, opts) {
    opts = opts || {};
    try {
        const res = await fetch('/api/approvals/mine');
        if (!res.ok) throw new Error();
        const reqs = await res.json();
        if (!reqs.length) {
            if (opts.hideWhenEmpty) { (opts.section || list).style.display = 'none'; return; }
            list.innerHTML = '<div class="empty">Nothing waiting for confirmation.</div>';
            return;
        }
        if (opts.section) opts.section.style.display = '';
        list.innerHTML = reqs.map(r => {
            const t = r._type === 'change' ? 'change' : 'agent';
            const key = `${t}-${r.id}`;
            const meta = t === 'change'
                ? `Change request · Risk: ${esc((r.risk_level || '').toUpperCase())}`
                : `Risk: ${esc((r.risk_level || '').toUpperCase())} · expires ${esc(new Date(r.expires_at).toLocaleString())}`;
            const confirmLabel = t === 'change' ? 'Confirm' : 'Confirm &amp; run';
            return `
            <div class="card req-card" id="req-${key}">
                <div class="req-tool">${esc(r.tool_name)}</div>
                <div class="req-reason">${esc(r.risk_reason)}</div>
                ${r.tool_name === 'grant_aws_permission' && r.tool_input && r.tool_input.policy
                    ? `<pre style="font-size:12px;white-space:pre-wrap;word-break:break-all;margin:6px 0;">${esc(JSON.stringify(r.tool_input.policy, null, 2))}</pre>${r.tool_input.mode !== 'self' && r.tool_input.manual && r.tool_input.manual.cli ? `<pre style="font-size:12px;white-space:pre-wrap;word-break:break-all;margin:6px 0;">${esc(r.tool_input.manual.cli)}</pre>` : ''}`
                    : ''}
                <div class="req-meta">${meta}</div>
                <div class="req-actions">
                    ${r.can_confirm
                        ? `<button class="btn-run" data-act="confirm" data-type="${t}" data-id="${r.id}">${confirmLabel}</button>`
                        : `<span class="req-wait">Waiting for an owner or admin of your organization</span>`}
                    <button class="btn-cancel" data-act="cancel" data-type="${t}" data-id="${r.id}">Cancel request</button>
                </div>
                <div class="req-status" id="status-${key}"></div>
            </div>`;
        }).join('');
    } catch (e) {
        list.innerHTML = '<div class="empty">Couldn’t load your requests. Refresh to try again.</div>';
    }
}

async function myRequestAct(type, id, action) {
    const key = `${type}-${id}`;
    const card = document.getElementById(`req-${key}`);
    card.querySelectorAll('button').forEach(b => b.disabled = true);
    const status = document.getElementById(`status-${key}`);
    status.textContent = action === 'confirm' ? (type === 'change' ? 'Confirming…' : 'Running…') : 'Cancelling…';
    const url = type === 'change'
        ? `/api/changes/${id}/${action === 'confirm' ? 'approve' : 'reject'}`
        : `/api/approvals/${id}/${action}`;
    const body = type === 'change' && action === 'cancel' ? {reason: 'Cancelled by requester'} : {};
    try {
        const res = await fetch(url, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!data.success) {
            status.style.color = '#ef4444';
            status.textContent = data.error || 'Something went wrong.';
            card.querySelectorAll('button').forEach(b => b.disabled = false);
            return;
        }
        if (action === 'cancel') {
            status.style.color = 'var(--text-secondary)';
            status.textContent = 'Cancelled. Nothing was changed.';
        } else if (type === 'change') {
            status.style.color = '#10b981';
            status.innerHTML = 'Confirmed. Run it from <a href="/changes">Change history</a>.';
        } else {
            const ok = (data.result || {}).success !== false;
            status.style.color = ok ? '#10b981' : '#ef4444';
            status.textContent = ok ? 'Done. The result is also in the chat.' : 'Ran, but returned an error: ' + ((data.result || {}).error || 'unknown');
        }
    } catch (e) {
        status.style.color = '#ef4444';
        status.textContent = 'Network error. Refresh to see the current state.';
    }
}


document.addEventListener('click', function (e) {
    const btn = e.target.closest && e.target.closest('.req-actions button[data-act]');
    if (!btn) return;
    myRequestAct(btn.dataset.type, parseInt(btn.dataset.id, 10), btn.dataset.act);
});
