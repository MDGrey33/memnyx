---
name: cmux-browse
description: Drive a real web browser through cmux's built-in snapshot-driven browser automation — open/navigate, read via accessibility snapshots, click/fill/select forms, attach files, log in via cookies/profile import, screenshot, and submit. Use this instead of a permission-gated browser MCP for filling and submitting web forms (job applications, ATS portals, dashboards) — cmux has no per-domain permission wall, which is what typically blocks that kind of MCP. Trigger on "use the cmux browser", "drive the browser", "fill this form", "submit this application in the browser", "cmux browse", or any task that needs autonomous web-form interaction. Works the same way for any assistant driving the shared cmux CLI, Claude Code or otherwise.
user_invocable: true
---

# cmux-browse — autonomous web control via the cmux browser

cmux ships a **Playwright-grade browser panel** driven entirely through the cmux CLI. Unlike a
typical browser-control MCP, it has **no per-domain "Permission denied by user" prompts** — that
wall is the exact thing that blocks fully autonomous form-filling in other setups. Use this for any
fill-and-submit web work.

Verified working end-to-end on a real multi-step job-application form.

## Binary + invocation

```
CMUX=/Applications/cmux.app/Contents/Resources/bin/cmux
# Most subcommands REQUIRE a surface handle: pass --surface surface:N (or as first positional).
$CMUX browser --surface surface:218 <subcommand> ...
```
Helper used throughout: `B(){ CMUX_QUIET=1 $CMUX browser --surface surface:218 "$@"; }`

Browser must be enabled: `$CMUX browser-status` → `enabled` (else `$CMUX enable-browser`).

## 1. Open / navigate

```
$CMUX browser open "<url>" --workspace workspace:4 --focus false   # → prints surface=surface:N (reuse it)
B navigate "<url>" --snapshot-after
B get-url            # current URL
B back | forward | reload
```
`open` reuses an existing browser surface in the workspace (placement=reuse). Capture the printed
`surface:N` — every later call needs it.

## 2. Read the page — snapshot is your eyes

```
B snapshot -i                       # interactive accessibility tree with [ref=eN] handles
B snapshot -i --compact --max-depth 8
B get text  --selector '<css>'
B get html  --selector '<css>'
B get value --selector '<css>'
B eval '<javascript>'               # run page JS, returns the result
B eval --script "$(cat /tmp/foo.js)"  # for large scripts
B screenshot --out /path/shot.png
```
The snapshot prints elements as `- textbox "First" [ref=e57]`. Use refs to click; use stable CSS
(`[name=...]`) to fill.

## 3. Interact — clicks, fills, selects

**CRITICAL selector rule:** the engine takes **CSS selectors only**. Playwright shorthands
`text=...` and `:has-text(...)` are NOT valid here and throw `not a valid selector`.

- **Click** — by ref (from a fresh snapshot) or CSS:
  ```
  B click e27 --snapshot-after          # by ref (positional) — reliable
  B click --selector '#submit'          # by css
  B eval '[...document.querySelectorAll("button")].find(b=>/submit application/i.test(b.innerText))?.click()'  # by text via JS
  ```
- **Fill text** — prefer stable `[name=...]` CSS (refs renumber on every snapshot):
  ```
  B fill --selector '[name="first_name"]' --text 'Jane'
  ```
- **Select dropdown** — needs the option *value*, not its label. Get values first:
  ```
  B eval 'Array.from(document.querySelector("[name=foo]").options).map(o=>({v:o.value,t:o.text}))'
  B select --selector '[name="foo"]' --value '<option-value>'
  ```
- **Map all inputs** at once (best first move on a form — gives stable names + required flags):
  ```
  B eval 'Array.from(document.querySelectorAll("input,textarea,select")).map(e=>({tag:e.tagName,type:e.type,name:e.name,placeholder:e.placeholder,required:e.required}))'
  ```

**Gotchas learned:** refs (`eN`) renumber on EVERY snapshot — never reuse a ref from an old
snapshot; either click immediately after snapshotting, or address fields by `[name=...]`. Subcommands
silently misparse if `--surface` is omitted ("requires a subcommand").

## 4. File attachment — the hard part, two paths

cmux's CLI does **NOT** expose Playwright's `setInputFiles`. So:

**Path A — DOM injection (works for simple forms that read `input.files` on change):**
Inject the file as a base64 blob via DataTransfer. Proven to populate the input and render the
filename in the UI.
```bash
CV=/path/file.pdf
B64=$(base64 < "$CV" | tr -d '\n')
cat > /tmp/up.js <<JS
(() => {
  const b64="$B64", bin=atob(b64), arr=new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
  const f=new File([arr],"file.pdf",{type:"application/pdf"});
  const dt=new DataTransfer(); dt.items.add(f);
  const inp=document.querySelector('[name="documents.cv"]');
  inp.files=dt.files;
  inp.dispatchEvent(new Event('change',{bubbles:true}));
  inp.dispatchEvent(new Event('input',{bubbles:true}));
  return inp.files.length+":"+inp.files[0].name;
})()
JS
B eval --script "$(cat /tmp/up.js)"
```
**LIMIT:** strict React AJAX uploaders (common on ATS platforms like Personio, Ashby, or
Greenhouse-style forms) upload the file to their server on selection and submit a *token*. DOM
injection renders the filename but does NOT trigger their real upload XHR, so submit still errors
"please upload your CV" and the input clears. Confirm by checking `B network requests` for an
upload POST and whether the field survives a submit.

**Path B — real native file picker (works everywhere, needs one-time permission):**
Driving the macOS open-panel via `osascript`/System Events requires **Accessibility permission**
granted to the controlling process (System Settings → Privacy & Security → Accessibility). Once
granted:
```bash
B eval 'document.querySelector("[name=\"documents.cv\"]").click()'   # open native panel
osascript <<OSA
tell application "System Events"
  delay 0.6
  keystroke "g" using {command down, shift down}   -- Go to folder
  delay 0.6
  keystroke "$CV"
  delay 0.6
  keystroke return
  delay 0.8
  keystroke return                                  -- choose
end tell
OSA
```
If Accessibility is NOT granted, the keystrokes silently no-op (the panel stays empty). This is the
ONE setup step a human operator must do once to make file uploads fully hands-off; until then, for
strict uploaders either have them attach the file on the pre-filled form for a final manual submit,
or use Path A on lenient forms.

## 5. Logins / credentials

Public application forms (Personio, Lever, most ATS) need **no login**. When a site does:
```
B cookies set --name <n> --value <v> --domain <d> --url <url>
B state save /tmp/auth.json   # then  B state load /tmp/auth.json
B import --from chrome --domain <domain>   # import an existing browser session/profile
B profiles list|add|...
```
Never write credentials outside a dedicated secrets directory (e.g. `$HOME/.credentials/`); never
inline them in scripts or logs.

## 6. Submit + verify (never claim without proof)

```
B click <submit-ref>            # or eval-click by button text
B get-url                       # success pages usually change URL (e.g. .../success, /thanks, &apply→gone)
B eval '(()=>{let t=document.body.innerText;let m=t.match(/thank you|submitted|required|invalid/i);return m?m[0]:"none"})()'
B screenshot --out <assets-dir>/<company>-application/SUBMITTED-CONFIRMATION.png
```
A submission is "done" ONLY on a real confirmation page/screenshot. If it shows "required"/error,
scan for the specific message (`B eval` over short text nodes — exclude any JobPosting JSON-LD
schema block, which often itself contains the word "required") and fix the flagged field.

## Standard play (job application end-to-end)

1. `open` the apply URL → capture surface.  2. Click the page's Apply button (snapshot → click ref).
3. `eval` the input map (names + required).  4. `fill` text fields by `[name]`; `select` dropdowns by
option value.  5. Attach the file (Path A, or Path B if strict uploader).  6. Leave genuinely-unknown
optional fields blank — never invent facts about the applicant (e.g. a language proficiency level);
optional `required:false` fields can stay empty.  7. Click Submit.  8. Verify confirmation + screenshot.
9. Record the outcome wherever the task is being tracked; if blocked on the file-upload permission,
say so plainly.

## For other agents sharing the same machine

The cmux binary and every command above are identical for any other assistant (e.g. a second CLI
agent) running on the same box — it runs the same
`/Applications/cmux.app/Contents/Resources/bin/cmux browser ...` calls from its own shell. If more
than one assistant shares this machine, keep a pointer copy of this playbook somewhere both can
read. The same Accessibility caveat applies to file uploads regardless of which agent drives them.
