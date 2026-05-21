(function () {
  const VIEWS = new Set(['review', 'approved', 'skipped']);

  const getView = () => {
    const m = location.pathname.match(/^\/runs\/\d+\/(review|approved|skipped)\b/);
    return m && m[1];
  };
  const getRunId = () => {
    const m = location.pathname.match(/^\/runs\/(\d+)/);
    return m ? +m[1] : null;
  };
  const LIST_IDS = ['review-list', 'approved-list', 'skipped-list'];
  const getList = () => {
    for (const id of LIST_IDS) {
      const el = document.getElementById(id);
      if (el) return el;
    }
    return null;
  };
  const rows = () => {
    const l = getList();
    return l ? Array.from(l.querySelectorAll(':scope > div[hx-get]')) : [];
  };
  const selectedIndex = () => rows().findIndex(r => r.id === 'list-selected');

  function setSelectedRow(row) {
    if (!row) return;
    const list = row.parentElement;
    if (!list || !LIST_IDS.includes(list.id)) return;
    const cur = list.querySelector('#list-selected');
    if (cur && cur !== row) cur.removeAttribute('id');
    if (row.id !== 'list-selected') row.id = 'list-selected';
  }

  function selectIndex(i) {
    const rs = rows();
    if (i < 0 || i >= rs.length) return;
    setSelectedRow(rs[i]);
    rs[i].click();
    rs[i].scrollIntoView({ block: 'nearest' });
  }

  // Capture-phase delegate: any click on a list row (including the user's own
  // clicks) moves the list-selected id so subsequent W/S/A/D act on it.
  document.addEventListener('click', e => {
    const row = e.target.closest && e.target.closest('div[hx-get]');
    if (!row) return;
    setSelectedRow(row);
  }, true);

  function isTyping(t) {
    if (!t) return false;
    if (t.isContentEditable) return true;
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName);
  }

  const DECIDED_CLASSES = ['row-decided-approve', 'row-decided-reject'];

  function markDecided(row, status) {
    if (!row) return;
    row.classList.remove(...DECIDED_CLASSES);
    row.classList.add(status === 'APPROVED' ? 'row-decided-approve' : 'row-decided-reject');
  }
  function clearDecided(row) {
    if (!row) return;
    row.classList.remove(...DECIDED_CLASSES);
  }

  function act(status) {
    if (document.body.classList.contains('static-export')) return;
    if (document.body.classList.contains('run-uploaded')) return;
    if (!VIEWS.has(getView())) return;
    const runId = getRunId();
    if (runId == null) return;
    const rs = rows();
    const i = selectedIndex();
    let cid, row;
    if (i >= 0) {
      row = rs[i];
      const m = (row.getAttribute('hx-get') || '').match(/\/(\d+)$/);
      if (!m) return;
      cid = m[1];
    } else {
      // No list row selected — e.g. a permalink to an auto-approved
      // candidate, which the default queue filter excludes. Fall back to
      // the candidate shown in the detail pane (the decision form's URL).
      const form = document.querySelector('form[hx-post*="/review/"]');
      const m = form && (form.getAttribute('hx-post') || '').match(/\/(\d+)$/);
      if (!m) return;
      cid = m[1];
    }
    if (row) markDecided(row, status);
    fetch(`/runs/${runId}/review/${cid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ status }).toString(),
    })
      .then(r => {
        if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
        if (i >= 0) {
          const next = i + 1 < rs.length ? i + 1 : i;
          if (next !== i) selectIndex(next);
        } else {
          // No queue to advance through; reload so the new decision
          // state is visible in the Decision pane.
          window.location.reload();
        }
      })
      .catch(err => {
        if (row) clearDecided(row);
        console.error('review-keys:', err);
        alert('Decision failed: ' + err.message);
      });
  }

  let neighborMsgTimer = null;
  function neighborMsg(text) {
    const el = document.getElementById('neighbor-msg');
    if (!el) return;
    el.textContent = text;
    if (neighborMsgTimer) clearTimeout(neighborMsgTimer);
    neighborMsgTimer = setTimeout(() => { el.textContent = ''; }, 4000);
  }

  // Neighbour nav works on any run page (main run view + review trio), not
  // just the list views — so you can press N/M (or click the buttons) right
  // after uploading, when you're back on the run view. A null result means
  // no adjacent tile has a run still needing review (or this run isn't
  // tile-aligned); say so instead of failing silently.
  function jumpNeighbor(direction) {
    if (document.body.classList.contains('static-export')) return;
    const runId = getRunId();
    if (runId == null) return;
    fetch(`/runs/${runId}/neighbor?dir=${direction}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(j => {
        if (j && j.run_id != null) {
          window.location.href = `/runs/${j.run_id}/review#select-first`;
        } else {
          const msgs = {
            prev: 'No earlier neighbouring tile still needs review.',
            next: 'No further neighbouring tile still needs review.',
            hardest: 'No other tile with items for review found.',
            easiest: 'No other tile with items for review found.',
          };
          neighborMsg(msgs[direction] || 'No eligible tile found.');
        }
      })
      .catch(err => {
        console.error('review-keys:', err);
        neighborMsg('Neighbour lookup failed.');
      });
  }

  // Click delegate for the visible Prev/Next buttons — same code path as
  // the N/M hotkeys, so there is one source of truth.
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('[data-neighbor]');
    if (!b) return;
    e.preventDefault();
    jumpNeighbor(b.getAttribute('data-neighbor'));
  });

  // Upload chord: `g` then `u`. A bare key would fire a real, irreversible
  // OSM changeset on one stray press, so we require a deliberate two-key
  // sequence. The upload button's own `disabled` state (uploaded / nothing
  // APPROVED) is the single source of truth — the chord never bypasses it.
  let chordArmed = false;
  let chordTimer = null;

  function disarmChord() {
    chordArmed = false;
    if (chordTimer) { clearTimeout(chordTimer); chordTimer = null; }
    const hint = document.getElementById('upload-chord-hint');
    if (hint) hint.hidden = true;
  }
  function armChord() {
    chordArmed = true;
    const hint = document.getElementById('upload-chord-hint');
    if (hint) hint.hidden = false;
    if (chordTimer) clearTimeout(chordTimer);
    chordTimer = setTimeout(disarmChord, 1500);
  }
  function uploadRun() {
    disarmChord();
    if (document.body.classList.contains('static-export')) return;
    if (document.body.classList.contains('run-uploaded')) return;
    if (!VIEWS.has(getView())) return;
    const form = document.getElementById('upload-bar-form');
    const btn = form && form.querySelector('button');
    if (!form || !btn || btn.disabled) return;
    const runId = getRunId();
    if (runId == null) return;
    if (btn.dataset.uploading === '1') return;
    btn.dataset.uploading = '1';
    btn.textContent = 'Uploading…';
    fetch(`/runs/${runId}/upload`, { method: 'POST' })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        window.location.reload();
      })
      .catch(err => {
        btn.dataset.uploading = '0';
        btn.textContent = 'Upload to OSM';
        console.error('review-keys:', err);
        alert('Upload failed: ' + err.message);
      });
  }

  function selectFirstIfHinted() {
    if (location.hash !== '#select-first') return;
    if (!VIEWS.has(getView())) return;
    const rs = rows();
    if (rs.length) selectIndex(0);
    // Clear the hint so a manual refresh doesn't keep re-selecting.
    history.replaceState(null, '', location.pathname + location.search);
  }
  // Must run AFTER htmx has bound its click handlers (htmx processes on
  // DOMContentLoaded; this script is `defer`, so it executes before that).
  // window.load fires after htmx processing, so .click() on the row will
  // actually trigger the hx-get instead of just the inline visual handler.
  if (document.readyState === 'complete') {
    selectFirstIfHinted();
  } else {
    window.addEventListener('load', selectFirstIfHinted, { once: true });
  }

  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (isTyping(e.target)) return;
    if (document.body.classList.contains('static-export')) return;
    if (getRunId() == null) return;
    const k = e.key.toLowerCase();
    // Neighbour nav is allowed on any run page (incl. the main run view).
    if (k === 'n') { e.preventDefault(); jumpNeighbor('prev'); return; }
    if (k === 'm') { e.preventDefault(); jumpNeighbor('next'); return; }
    if (k === 'k') { e.preventDefault(); jumpNeighbor('hardest'); return; }
    if (k === 'l') { e.preventDefault(); jumpNeighbor('easiest'); return; }
    // Everything below is list-driven and only applies to the review trio.
    if (!VIEWS.has(getView())) return;
    if (k === 'g') { e.preventDefault(); armChord(); return; }
    if (chordArmed) {
      disarmChord();
      if (k === 'u') { e.preventDefault(); uploadRun(); return; }
      // any other key: chord broken, fall through to normal handling
    }
    if (k === 'w') { e.preventDefault(); selectIndex(selectedIndex() - 1); }
    else if (k === 's') { e.preventDefault(); selectIndex(selectedIndex() + 1); }
    else if (k === 'a') { e.preventDefault(); act('APPROVED'); }
    else if (k === 'd') { e.preventDefault(); act('REJECTED'); }
  });

  window.t2ReviewKeys = { act };
})();
