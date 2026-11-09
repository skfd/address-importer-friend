# Republishing a proposal to the OSM wiki

Republishing `IMPORT_PROPOSAL.mediawiki` to the OSM wiki via the browser is
approved. Approving the republish is enough — no second pause at Save.

**Use Claude in Chrome, not the built-in browser.** The built-in browser pane
is isolated and shows "View source"; Chrome carries the `Skfd` wiki login.

**Getting 50k characters into the edit box** — do not retype the file:

1. Serve the scratchpad over HTTP from **PowerShell**, not Bash. A server
   started by the Bash tool binds inside the sandbox and is invisible to
   Chrome.
2. Use `ThreadingTCPServer`. A plain `TCPServer` deadlocks after one
   keep-alive connection and every later request hangs.
3. Send `Content-Type: text/plain; charset=utf-8`. Without the charset Chrome
   decodes as latin-1, and the em dashes are silently destroyed — the byte
   count still matches, so only a hash catches it.
4. Carry the text across origins with `window.name`: navigate the tab to the
   local file, `window.name = pre.textContent`, navigate to the edit page,
   assign into `#wpTextbox1`. An in-page `fetch` of the local file hung for
   45s from both the wiki page and the localhost page; the cause was never
   isolated, and the single-threaded server in (2) explains it on its own.
   `window.name` sidesteps the question.
5. **Verify by SHA-256** in the browser against the local file before saving,
   and again with `action=raw` after. Length alone is not enough.

**Diff live against the repo before overwriting** — the repo runs ahead. On
2026-09-18 the live page was still showing the superseded ~3,699
`addr:province` figure. Confirm the drift is ours and not a third party's
edit, then overwrite wholesale.
