---
name: setup-aws-mcp
description: Install and configure the managed AWS MCP Server for Claude Code
user_invocable: true
---

# Setup AWS MCP — AWS API Access for Claude Code

You are helping the user get the **AWS MCP Server** running with Claude Code. Walk through setup interactively, detecting what's already installed and what needs to be done.

The AWS MCP Server is AWS's managed, remote MCP server. Claude Code reaches it through a local stdio proxy, `mcp-proxy-for-aws`, launched via `uvx`. The proxy reads the standard AWS credential chain and performs SigV4 signing locally — nothing is hosted on the user's machine except the proxy. It supersedes the deprecated `awslabs.aws-api-mcp-server`; Step 1 detects a stale entry and Step 4 replaces it.

## Model Selection

See `.claude/skills/_shared/MODEL_SELECTION.md` (in your workspace) for full policy.

- **Default model:** Sonnet — interactive setup is judgment work: reading an existing `.mcp.json`, diagnosing credential and endpoint failures, deciding whether an existing profile is fit to reuse
- **Deterministic parts:** prerequisite detection (`uvx --version`, `which uvx`), `.mcp.json` merge, `.gitignore` check — scripts, not LLM calls
- **Promote to Opus when:** never — no decision here is architectural
- **Demote to Haiku when:** never — this skill's two failure modes are both silent and both consequential: a misconfigured region answers confidently about the wrong resources while every check passes, and an over-permissioned profile hands the agent write access to production while looking like a working setup. Neither announces itself; catching them is judgment, not pattern-matching

## Step 1: Check Prerequisites

Detect what's available on this machine:

- **uvx** — run `uvx --version`. If missing, `uv` needs to be installed first. Search the web for current uv installation instructions for the user's detected OS/platform.
- **AWS CLI** — run `aws --version`. Used for creating/verifying the profile in Step 2. If missing, search the web for current AWS CLI v2 installation instructions for the user's platform.
- **Resolve the absolute path to uvx** — run `which uvx`. The MCP config requires a fully expanded absolute path (e.g., `/Users/username/.local/bin/uvx`). Do not use `~`, `$HOME`, or relative paths — Claude Code does not expand them.
- **Whether `.mcp.json` already exists** in the project root (and whether it already has an `aws-mcp` entry — note if it still points at the deprecated `awslabs.aws-api-mcp-server`).
- **Whether a new *major* of the proxy has shipped** — read `info.version` from `https://pypi.org/pypi/mcp-proxy-for-aws/json` and compare its major against the pinned range in Step 4. This exists because Step 4 asserts internals of 1.x and says a major bump must force re-verification; without this check that instruction has no trigger and would never fire.

  Only a **major** is worth reporting. The pin is a range, not a fixed version, so new 1.x releases are already picked up automatically — announcing them would be noise on every release. If a 2.x exists, tell the user plainly and leave it to them:

  > mcp-proxy-for-aws 2.x is available; this skill pins `>=1.6,<2`. Its region and credential guidance was verified against 1.x internals, so those need re-checking against 2.x before the range is widened — raise with whoever maintains this skill.

  Never widen the range yourself on the strength of a version number. If PyPI is unreachable, skip the check silently and carry on — a version check must never block setup.

Report findings to the user before proceeding.

## Step 2: Configure AWS Profile — the read-only guardrail

The MCP server signs with a dedicated AWS CLI profile. **This IAM profile is the security boundary.** AWS enforces its permissions server-side on every call, no matter which MCP tool is invoked (including the sandboxed `run_script` tool). A read-only profile is therefore the reliable way to keep the server read-only — see the note at the end of Step 4 on why the proxy's `--read-only` flag is *not* a substitute.

**Scope first, mechanism second.** `--read-only` is unusable and `call_aws` runs any AWS CLI command, so a profile that *can* write means an agent that *can* write. Everything below follows from that: what the credentials are permitted to do is the decision that matters, and how they are obtained (static key, SSO) is secondary. Settle the scope, then pick the mechanism — never the reverse.

1. **Check for existing profiles**: Run `aws configure list-profiles` to see what's already configured.

2. **Ask the user** which profile to use:
   - Suggest `aws-mcp-readonly` as a name — a suggestion, not a requirement; the user may want a different name or an existing profile
   - If the user picks an existing profile, confirm it works: `aws sts get-caller-identity --profile <name>`

   On what "read-only" should mean here — **`ReadOnlyAccess` is not config-only. It reads data.** It grants `s3:Get*`, `dynamodb:Get*`, `ssm:Get*`, `sqs:Receive*` and their equivalents across thousands of actions, so attaching it points the MCP server at every object and record in the account, not just at infrastructure metadata. (It does withhold `secretsmanager:GetSecretValue`.) That is often not what someone means when they say they want a read-only profile, and on an account holding personal or regulated data it is the difference between "the agent can see my infrastructure" and "the agent can read my customers".

   Surface the choice rather than deciding it:
   - **`ViewOnlyAccess`** (`arn:aws:iam::aws:policy/job-function/ViewOnlyAccess`) — lists and describes resources plus basic metadata, without the data reads. Usually the right fit for infrastructure questions.
   - **`ReadOnlyAccess`** — appropriate when the user genuinely wants the agent reading bucket and table contents.
   - **A scoped policy** — narrower still. Do not invent an action list for the user; their estate determines it, and a list guessed here would rot.

   Ask which they want, and say plainly what each admits. If they already have a profile, say what its policy actually grants rather than assuming its name is accurate.

3. **Settle the resource region** — where the user's AWS resources actually live. This is the value that ends up in `--metadata AWS_REGION=` (Step 3 explains why it is load-bearing and why omitting it fails silently).

   If reusing an existing profile, read what it already declares — `aws configure get region --profile <name>` — and offer that as the default. It is the user's own prior answer, so it beats any guess.

   Otherwise ask **"Which region are your resources in?"**, offering these as selectable options while accepting any region code the user types instead:

   - `eu-west-2` — Europe (London)
   - `us-east-1` — US East (N. Virginia)

   The two options are a convenience shortlist, not the permitted set — AWS has far more regions and the user's may not be listed. Never infer the region from the user's locale, the endpoint choice, or a default; an unstated region is a question to ask, not a blank to fill.

4. **Create the profile** if needed — **the user runs this themselves, in their own terminal**.

   The scope was settled when the profile was chosen above, and is not up for renegotiation here — this is only about how the credentials are obtained.

   **Default to a dedicated read-only IAM user with a static access key.** Its whole appeal is that its permissions are chosen for this purpose and nothing else — a purpose-built principal cannot accidentally inherit a human's day job:

   ```
   aws configure --profile <name>
   ```

   It prompts for the access key ID, secret access key, region, and output format, and writes both `~/.aws/credentials` and `~/.aws/config` correctly, merging with any existing profiles. Tell the user to give it the resource region settled just above when it asks.

   **IAM Identity Center (SSO) — offer this only after the above, and only with the gate below.** An SSO profile works fine mechanically (the proxy uses the standard boto3 chain, so no special handling), and per-request credential resolution means `aws sso login` fixes an expired session with no Claude Code restart. Requests made while it is expired fail with a credentials error, not something subtler.

   ```
   aws configure sso --profile <name>     # then: aws sso login --profile <name>
   ```

   **The gate: an SSO profile assumes whatever permission set the user already has, and for most engineers that is their everyday working role — usually write or administrator.** Wiring that in hands the agent exactly the power this skill exists to withhold, while *looking* like a security improvement because no secret touched the disk. Use SSO only with a permission set scoped to read-only. If the organisation has no such permission set, that is a request to make of whoever administers Identity Center — not something to work around here, and not a reason to fall back on an admin role "just for now".

   **Do not present SSO as the recommended option, and do not lead with it.** People pick the first choice offered and skim the caveat under it; ordering changes behaviour in a way a warning does not. Lead with the read-only IAM user, and raise SSO as the alternative it is.

   Note the common argument for SSO — "no long-lived secret on disk" — is weaker than it sounds. It assumes static keys are never rotated, which is false wherever the organisation rotates them automatically. Credential hygiene is a real but secondary axis; permission scope is the one that decides whether an agent can delete production.

   **Never ask the user to paste the access key or secret into the conversation, and never run this command for them** — not via the Bash tool (it is interactive and will hang with no stdin), and not via Claude Code's `!` prefix (which exists to pull command output *into* the conversation, and `aws configure` echoes the secret unmasked). The secret must never enter the transcript or shell history. Ask the user to run it and tell you when it's done; you verify by identity below, never by reading the key.

   > **Hardening (optional).** This leaves the secret in `~/.aws/credentials` in plaintext (mode 0600) — the standard AWS credential-chain location. To keep it in the macOS Keychain instead, store it with `security add-generic-password -U -a "$USER" -s <name> -w` and point the profile at a `credential_process` in `~/.aws/config` that shells out to `security find-generic-password -w -s <name>`. boto3's chain (which the proxy uses) resolves `credential_process` natively.
   >
   > Whether the extra moving part is worth it depends on the scope chosen for the profile above, so weigh it against that rather than against "it's only read-only": a leaked `ViewOnlyAccess` key exposes infrastructure metadata, while a leaked `ReadOnlyAccess` key on an account holding personal or regulated data exposes the data itself.

5. **Verify the profile works, and verify what it can do**: Run `aws sts get-caller-identity --profile <name>`. Confirm the ARN is the identity the user expects — and do not stop there. **A profile's name is not evidence of its permissions**; `aws-mcp-readonly` can be attached to anything.

   Read the scope out of the ARN, which reports it in both cases:

   - **`arn:aws:sts::<acct>:assumed-role/AWSReservedSSO_<PermissionSet>_<suffix>/<user>`** — an SSO session. The permission set name is right there in the ARN. Show it to the user and ask them to confirm it is read-only. If it reads `AdministratorAccess`, `PowerUserAccess`, or anything else that plainly grants writes, **stop and say so**: this configuration would let the agent modify production. Do not proceed on the assumption that a permission-set name is accurate either — it is a strong signal, not proof.
   - **`arn:aws:iam::<acct>:user/<name>`** — a static-key IAM user. Its policies are checkable directly: `aws iam list-attached-user-policies --user-name <name> --profile <name>`. If the call is itself denied, say so plainly rather than assuming the profile is safe — an unverifiable scope is a reason to ask the user, not to continue quietly.

   If verification fails, troubleshoot with the user before proceeding.

## Step 3: Regions — endpoint vs resource

Two regions are in play and they are **not** the same thing. Conflating them is this skill's main hazard:

- **Resource region** — where the user's AWS resources live. Already settled in Step 2; do not re-ask. Becomes `--metadata AWS_REGION=`.
- **Endpoint region** — where the MCP control plane runs. Settled here. Determines the endpoint URL, and the proxy derives its signing region from it.

The AWS MCP Server is reached at a regional control-plane endpoint. Available endpoints (confirm the current list by web search if unsure — AWS adds regions over time):

- `eu-central-1` (Frankfurt) → `https://aws-mcp.eu-central-1.api.aws/mcp` — recommended for EU users
- `us-east-1` → `https://aws-mcp.us-east-1.api.aws/mcp`

Ask the user which endpoint to use. Recommend the endpoint nearest their resource region — `eu-central-1` for EU resources, including London (`eu-west-2`), since there is no eu-west-2 endpoint. **The two regions need not match, and often cannot:** endpoint `eu-central-1` with resources in `eu-west-2` is normal and correct. Do not "fix" a mismatch by aligning them.

### The signing region is derived — do not pass `--region`

The proxy resolves its signing region in `determine_aws_region(endpoint, region)` (`utils.py`), in this order: **explicit `--region` → parsed from the endpoint URL → `AWS_REGION` env var → error**.

Two consequences, both verified against v1.6.3 source and live:

- **`--region` is redundant** for any well-formed endpoint URL, because the URL already contains the region and the parser picks it up. Omit it. The config then has exactly *one* region knob (`--metadata AWS_REGION=`, the resource region) instead of two look-alike ones, which removes the mix-up rather than documenting it.
- **`--region` is an unvalidated override.** When passed, it is returned verbatim and never checked against the endpoint host — so `--region us-east-1` against the `eu-central-1` endpoint does not error; it completes the handshake and enumerates every tool. A wrong `--region` fails silently or not at all, which is precisely why it is safer not to pass one.

### `--metadata AWS_REGION=` is mandatory

`server.py` builds the metadata dict as `{'AWS_REGION': region}` — seeding it with the **signing** region — and only then merges the user's `--metadata` over the top. So if `--metadata AWS_REGION=` is omitted, the resource region silently **defaults to the endpoint's region**: an EU user on the Frankfurt endpoint queries `eu-central-1` resources while believing they are querying `eu-west-2`. Confirmed live — `describe-availability-zones` with no `--metadata` returns Frankfurt AZs, with no warning.

Always pass `--metadata AWS_REGION=<resource-region>` explicitly, even when it looks redundant.

## Step 4: Write `.mcp.json` Entry

Merge the following entry into `.mcp.json` in the project root, using the actual values from earlier steps:

```json
{
  "aws-mcp": {
    "command": "<absolute-path-to-uvx>",
    "args": [
      "--from", "mcp-proxy-for-aws>=1.6,<2",
      "mcp-proxy-for-aws",
      "<endpoint-url>",
      "--profile", "<chosen-profile-name>",
      "--metadata", "AWS_REGION=<resource-region>"
    ]
  }
}
```

Example (EU: Frankfurt endpoint, London resources, read-only profile):

```json
{
  "aws-mcp": {
    "command": "/Users/username/.local/bin/uvx",
    "args": [
      "--from", "mcp-proxy-for-aws>=1.6,<2",
      "mcp-proxy-for-aws",
      "https://aws-mcp.eu-central-1.api.aws/mcp",
      "--profile", "aws-mcp-readonly",
      "--metadata", "AWS_REGION=eu-west-2"
    ]
  }
}
```

**Rules**:
- Use the **absolute path** to `uvx` from Step 1 — never `~`, `$HOME`, or bare `uvx`
- The **endpoint URL is a positional argument and must come first**, before any `--flags`
- **Pin the major with `--from`, not with `@`.** This skill's region guidance is not generic advice — it asserts specific internal behaviour of the proxy (how `determine_aws_region` resolves, how `server.py` seeds the metadata dict), established by reading 1.x source. `@latest` would silently carry installers onto a future major where those claims may no longer hold, failing in the quiet wrong-region way this skill exists to prevent. `--from 'mcp-proxy-for-aws>=1.6,<2'` still takes every 1.x fix; it refuses only a major bump — exactly the event that should force a human to re-verify these claims and update this skill.

  **Do not "simplify" this to `mcp-proxy-for-aws@1`.** uv reads `@` as an *exact* version, so `@1` resolves to `1.0.0` — the oldest 1.x, which predates `--metadata` and dies on startup with `unrecognized arguments`. `@` cannot express a range; `--from` is the only shape that does. When using `--from`, the package name must still be repeated as the command to run, before the endpoint URL.
- **No `--region`** — the proxy derives the signing region from the endpoint URL, and passing it adds an unvalidated second region knob that looks interchangeable with the resource region. See Step 3. (An existing config that passes a `--region` matching its endpoint is harmless and need not be changed; just don't add one.)
- **`--metadata AWS_REGION=<resource-region>` is required, not optional.** Omit it and the resource region silently falls back to the endpoint's region — the calls succeed against the wrong region with no error. See Step 3.
- The profile is passed as `--profile`. Passing it via an `AWS_PROFILE` env var also works as a fallback, but the flag is explicit.
- **Credentials are re-read from disk on every request** (at the pinned `>=1.6` floor). `_sign_request_hook` in `sigv4_helper.py` calls `create_aws_session(profile)` per request rather than holding one session for the process lifetime, so profile switches and credential refreshes take effect on the next call with no restart. This is why the pin floor is 1.6 and not 1.0: early 1.x resolved credentials once in a factory that captured them into the auth object, and a refresh there *did* require a restart ([aws/mcp-proxy-for-aws#193](https://github.com/aws/mcp-proxy-for-aws/issues/193), fixed and closed 2026-06-02). Do not lower the floor below 1.6 without re-reading that hook.
- If `.mcp.json` already exists with other servers, **merge** — do not overwrite existing entries. If it has a stale `awslabs.aws-api-mcp-server` `aws-mcp` entry, replace it.

**Do NOT add `--read-only`.** The proxy's `--read-only` flag disables every tool whose `readOnlyHint` is `False` or unknown. The primary tool, `aws___call_aws`, runs *any* AWS CLI command (read or write), so it is annotated `readOnlyHint=False` and gets stripped — leaving only documentation/metadata tools and no ability to query AWS resources at all. Rely on the **read-only IAM profile** (Step 2) for the read-only guarantee instead; it keeps `call_aws` available for reads while AWS rejects any write server-side.

## Step 5: Ensure `.mcp.json` in `.gitignore`

Check `.gitignore` for `.mcp.json`. If not already listed, add it. The file is machine-specific and may contain secrets from other server configs.

## Step 6: Verify (pre-restart)

Run `/mcp-doctor --deep` to confirm the aws-mcp server starts and responds.

**Use `--deep`, not the default session mode.** Session mode reports on servers already loaded in the *current* session, and the entry just written to `.mcp.json` does not load until Claude Code restarts — so session mode would report `aws-mcp` ABSENT no matter how correct the config is. Deep mode launches the proxy as a subprocess and drives a real `initialize` + `list_tools` handshake, which is what makes it meaningful here: a healthy config enumerates the server's full tool set, and a bad profile fails the handshake outright.

**Do not hand-roll this check by running the proxy command directly in a shell.** It is a stdio server: with no MCP client on stdin it reads EOF and exits 0 with no output — *identically* for a good config, a nonexistent profile, and a garbage endpoint URL. A bare launch cannot fail, so it proves nothing. Only a real client handshake (what `--deep` does) distinguishes them.

**What `--deep` does *not* catch:** the resource region. A missing or wrong `--metadata AWS_REGION=` still completes the handshake and enumerates every tool — the server is perfectly healthy, it just answers about the wrong region. Deep mode validates credentials and reachability only; the region is Step 8's job.

If it fails, troubleshoot based on the error:
- Command not found: verify the absolute uvx path is correct
- AWS credential errors: re-check the profile with `aws sts get-caller-identity --profile <name>`
- Endpoint errors: confirm the endpoint URL is the first positional arg and the host is a real AWS MCP endpoint
- Package errors: try `uvx --refresh --from 'mcp-proxy-for-aws>=1.6,<2' mcp-proxy-for-aws --help`
- `unrecognized arguments: --metadata`: the proxy resolved to a pre-1.6 version — check the config uses `--from` with the range, not `@`

## Step 7: Report and restart

Summarize what was configured:

```
AWS MCP Setup Summary — NOT YET VERIFIED
========================================
uvx:          <path> (version)
AWS CLI:      <version>
Profile:      <profile-name>
Identity:     <ARN from sts get-caller-identity --profile>
Scope:        <permission set or attached policies, as verified in Step 2 — not the profile's name>
Endpoint:     <endpoint-region> (<endpoint-url>)
Resource region: <resource-region>
.mcp.json:    aws-mcp entry added / replaced
.gitignore:   .mcp.json entry present
Deep health check: passed / failed

Restart Claude Code for the new MCP server to load, then run Step 8 to verify it live.
```

Setup is **not** confirmed at this point — Step 8 is what confirms it. Do not report success until Step 8 passes.

## Step 8: Verify live, after the restart

Step 6 proves the proxy starts, authenticates, and serves tools. It does **not** prove the server answers against the right region — a missing or wrong `--metadata AWS_REGION=` silently queries the endpoint's region rather than erroring, and no earlier step can see it. That is what this step is for, and it is the reason setup is not confirmed until it passes.

The server's tools arrive **deferred** (name-only, no schema) — calling one directly fails with `InputValidationError`. Load the schema first with a `ToolSearch` `select:` query for `mcp__aws-mcp__aws___call_aws`, then run two probes:

1. **Identity through the proxy** — `aws sts get-caller-identity`. Confirms SigV4 signing, the endpoint, and the credential chain all work end-to-end, and that the ARN is the intended (read-only) principal. This is stronger than Step 2's check: that one proved the *profile* works, this one proves the *proxy path* works.
2. **Resource region** — any harmless region-scoped read that carries **no `--region` in the CLI command itself**, e.g. `aws ec2 describe-availability-zones`. It must be unqualified: hardcoding a region in the probe would mask the very fault being tested. The AZs returned must be in the resource region from Step 2. **If they come back in the endpoint's region, `--metadata AWS_REGION=` is missing or wrong** — that is the exact signature of the silent fallback described in Step 3, and it is the single most likely way this setup is quietly broken.

Both are reads and safe against any account. Do not probe write-denial by attempting a mutation — that means firing a write at the user's real account. If the user wants the IAM guardrail proven, hand them a command to run themselves and tell them to expect `AccessDenied`.

Report the live result:

```
AWS MCP Live Verification
=========================
Tool surface: aws___call_aws + <n> others loaded
Identity:     <ARN via proxy>  (expected: <read-only principal>)
Resource region: <region of returned AZs>  (expected: <resource-region>)
Status: verified / failed — <detail>
```

Run `/mcp-doctor` (session mode) anytime afterwards to re-check connectivity.
