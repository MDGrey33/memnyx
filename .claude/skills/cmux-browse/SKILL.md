---
name: cmux-browse
description: Drive a real web browser through cmux's built-in snapshot-driven browser automation — open/navigate, read via accessibility snapshots, click/fill/select forms, attach files, log in via cookies/profile import, screenshot, and submit. Use this instead of a permission-gated browser MCP for filling and submitting web forms (job applications, ATS portals, marketplace listings, dashboards) — cmux has no per-domain permission wall, which is what typically blocks that kind of MCP. Trigger on "use the cmux browser", "drive the browser", "fill this form", "submit this application in the browser", "cmux browse", or any task that needs autonomous web-form interaction. Not for reading a page that a plain web fetch can get; prefer it over the Chrome extension or the built-in browser only when per-domain approval would block the run. Works the same way for any assistant driving the shared cmux CLI, Claude Code or otherwise.
user_invocable: true
---

# cmux-browse — autonomous web control via the cmux browser

cmux has a browser panel driven entirely through its CLI, with **no per-domain "Permission denied
by user" prompts** — the wall that blocks unattended form-filling in other browser tools.

## Model Selection

See `.claude/skills/_shared/MODEL_SELECTION.md` (in your workspace) for full policy.

- **Default model:** Sonnet — reading snapshots, mapping fields to the user's facts, and judging whether a page is a real confirmation is judgment work
- **Deterministic parts:** the input map, option-value listing and confirmation-text check are `eval` one-liners — scripts, not LLM calls
- **Promote to Opus when:** deciding what personal data to enter into a form whose fields are ambiguous, or handling a credential/session import
- **Demote to Haiku when:** never for a run that submits; a read-only page scrape with a known selector may use it

## Binary + invocation

```
CMUX=/Applications/cmux.app/Contents/Resources/bin/cmux
SURF=surface:N        # the surface THIS task opened (see §1) — never a hard-coded number
B(){ CMUX_QUIET=1 $CMUX browser --surface "$SURF" "$@"; }
```
Most subcommands need the surface handle. Omitting `--surface` makes the CLI read your subcommand
as the surface, and it fails with "requires a subcommand".

Browser must be enabled: `$CMUX browser-status` → `enabled` (else `$CMUX enable-browser`).

**Only drive surfaces this task opened.** The user's logged-in sessions live in the same browser; never
navigate, click or close a tab they are using.

## 1. Open / navigate

```
$CMUX browser open "<url>" --focus false   # prints e.g. "OK surface=surface:N pane=pane:M placement=reuse"
B navigate "<url>" --snapshot-after
B wait --load-state complete               # or --url-contains <text> / --selector <css> / --text <text>
B get-url | back | forward | reload
```
Set `SURF` from what `open` prints. `open` can reuse an existing browser surface in the workspace
(`placement=reuse`); if that surface was showing the user's own page, say so before navigating away.
`$CMUX browser identify` also reports the surface.

## 2. Read the page — snapshot is your eyes

```
B snapshot -i                       # interactive accessibility tree with [ref=eN] handles
B snapshot -i --compact --max-depth 8
B get text  --selector '<css>'
B get value --selector '<css>'
B eval '<javascript>'               # run page JS; a string result comes back as raw text, not JSON
B eval --script "$(cat <scratchpad>/foo.js)"   # for longer scripts; keep each call under ~50 KB
B screenshot --out <path>.png
```
The snapshot prints elements as `- textbox "First" [ref=e57]`. Use refs to click; use stable CSS
(`[name=...]`) to fill.

**Frames:** many embedded forms (ATS apply widgets especially) sit in an iframe, where CSS
selectors find nothing. `B frame '<iframe css>'` switches into it; `B frame main` switches back.

## 3. Interact — clicks, fills, selects

`--selector` takes **CSS only**: Playwright shorthands `text=...` and `:has-text(...)` throw
`not a valid selector`. To locate by role or text, use the built-in finder.

- **Click** — by ref (from a fresh snapshot), by CSS, or by role/text:
  ```
  B click e27 --snapshot-after                      # by ref (refs work; --help documents only CSS)
  B click --selector '#submit'
  B find role button --name "Submit application"    # role/text/label/placeholder/testid finder; check `B find --help` for whether it acts or returns a handle
  ```
  Fallback when nothing else matches: `B eval` a `querySelectorAll(...).find(...)?.click()`.
- **Fill text** — prefer stable `[name=...]` CSS (refs renumber on every snapshot):
  ```
  B fill --selector '[name="first_name"]' --text 'Jane'
  ```
  Read the value back after filling; a stray click elsewhere can clear a field.
- **Select dropdown** — needs the option *value*, not its label. Get values first:
  ```
  B eval 'Array.from(document.querySelector("[name=foo]").options).map(o=>({v:o.value,t:o.text}))'
  B select --selector '[name="foo"]' --value '<option-value>'
  ```
- **Map all inputs** at once (best first move on a form — gives stable names + required flags):
  ```
  B eval 'Array.from(document.querySelectorAll("input,textarea,select")).map(e=>({tag:e.tagName,type:e.type,name:e.name,placeholder:e.placeholder,required:e.required}))'
  ```
- **Alerts and confirm boxes** block the page until handled: `B dialog accept` or `B dialog dismiss`.

Refs (`eN`) renumber on EVERY snapshot — never reuse a ref from an old snapshot; click immediately
after snapshotting, or address fields by `[name=...]`.

## 4. File attachment — three paths, in this order

**Path A — `set-input-files` (use first).** The CLI attaches real local files to a file input:
```bash
B set-input-files --selector 'input[type=file]' --file /path/a.jpg --file /path/b.jpg   # up to 128 files, 32 MiB
B set-input-files --selector 'input[type=file]' --clear
```
Verified 2026-11-17 on Facebook Marketplace's photo input: four JPEGs in one call, thumbnails
rendered, and the published listing carried the photos. Many sites give the input no `name` or id: tag
it first with `B eval 'document.querySelector("input[type=file]").setAttribute("data-cc","photos")'`
and select on `[data-cc=photos]` (an input accepting images and one accepting video can sit side by
side; pick by its `accept` value). Not yet tried on strict ATS uploaders: after attaching, confirm with
`B network requests` that an upload POST happened and that the field survives a submit.

**Path A2 — DOM injection (tiny files only).** Building a `File` from base64 inside `eval` and
setting `input.files` with a `DataTransfer` works only for small files: an `eval` argument over
about 50 KB breaks the socket ("Broken pipe"), and even 20-40 KB chunks fail unpredictably. It also
does not trigger a strict React uploader's real upload request (the filename shows, submit still says
"please upload", the input clears). Prefer Path A.

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
or use Path A2 on lenient forms with small files.

## 5. Logins / credentials

Public application forms (Personio, Lever, most ATS) need **no login**. When a site does, the user
logs in (phone codes and captchas are theirs); never log in for them. Session tools:
```
B cookies set --name <n> --value <v> --domain <d> --url <url>
B state save "$HOME/.credentials/cmux-<site>.json"   # session cookies ARE credentials: chmod 600, delete when the task ends
B state load "$HOME/.credentials/cmux-<site>.json"
B import --from chrome --domain <domain>             # import an existing browser session/profile
B profiles list|add|...
```
Never write credentials outside a dedicated secrets directory such as `$HOME/.credentials/`; never
inline them in scripts or logs.

## 6. Submit + verify (never claim without proof)

**Stop before anything irreversible.** Before Submit, Publish, Pay or Delete, show the user the filled
values and attachments (a screenshot is enough) and wait for their go — unless the task explicitly
authorised unattended submission. Never submit on a guess.

```
B click <submit-ref>            # or `find`, or eval-click by button text
B wait --url-contains <text>    # or --text / --load-state complete; don't read the page mid-transition
B get-url                       # success pages usually change URL (e.g. .../success, /thanks, &apply→gone)
B eval '(()=>{let t=document.body.innerText;let m=t.match(/thank you|submitted|required|invalid/i);return m?m[0]:"none"})()'
B screenshot --out <scope>/artifacts/<workstream-or-cmux-browse>/<site>-<YYYY-MM-DD>-confirmation.png
```
A submission is "done" ONLY on a real confirmation page/screenshot. If it shows "required"/error,
scan for the specific message (`B eval` over short text nodes — exclude any JobPosting JSON-LD
schema block, which often itself contains the word "required") and fix the flagged field. For a
bulk action (many deletes, many posts), the list on the page may not refresh: reload and count from
the fresh page, never from the loop's own tally.

## Standard play (job application end-to-end)

1. `open` the apply URL → set `SURF`.  2. Click the page's Apply button (snapshot → click ref); switch
into its iframe if the fields are not found.  3. `eval` the input map (names + required).  4. `fill` text
fields by `[name]`; `select` dropdowns by option value.  5. Attach the file: Path A; if no upload POST
appears, Path B; A2 only for tiny files on lenient forms.  6. Leave genuinely-unknown optional fields
blank — never invent facts about the applicant (e.g. a language proficiency level); optional
`required:false` fields can stay empty.  7. Show the user the filled form and wait for their go, unless
unattended submission was authorised.  8. Click Submit, `wait`, verify the confirmation and
screenshot it.  9. Record the outcome wherever the task is being tracked; if blocked on the file-upload
permission, say so plainly.
