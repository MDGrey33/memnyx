---
name: second-opinion
description: Dual-model review — runs the same question past a second, independent reasoner (a separate model/CLI, e.g. Codex) and synthesizes the disagreements with the primary Claude take. Use before an irreversible call — architecture, security, strategy, high-blast-radius code. Trigger phrases "second opinion", "/second-opinion", "review this", "get another perspective", "sanity check this plan".
user_invocable: true
args: Optional. `<review-type> "<topic or file path>"`. Review types — plan, architecture, security, strategy, decision, code. Default = decision.
---

## Requirements

This skill needs a second model available on the machine, independent of the Claude session running it — a separate CLI you can invoke as a subagent or shell command (e.g. the OpenAI Codex CLI, Gemini CLI, or any other model runtime you have installed and authenticated). If no second model is available, see **Error handling** below — this skill degrades gracefully to a labeled single-model review rather than blocking.

## Model Selection

- **Default model for the primary pass:** your strongest reasoning model — the whole point is high-stakes judgment, and the premium of a stronger model is cheap insurance against a bad call.
- **Demote to a lighter model when:** review type is `code` or `plan` and the scope is small (one file, one decision).

## Disambiguate

| Use | Tool |
|---|---|
| "Is this the right approach?" judgment calls | `/second-opinion` (this skill) |
| "Is this claim accurate?" data verification | a fact-checking skill, if you have one |
| "Does this diff pass security?" diff-time | a security-review skill, if you have one |
| "Is there anything we're missing in the design?" before code | a threat-modeling skill, if you have one |

## When to invoke

- Before an irreversible architectural or infrastructure decision
- When a plan has cross-team blast radius
- Auth / payments / credentials / data-handling code before merge
- Strategy calls where trade-offs are unclear
- Any time you (or the user) feel uncertain and want a structured second take

Don't invoke for:
- Simple implementation tweaks the current thread can finish
- Fact lookup (use a fact-checker skill if you have one)
- Code review of a diff you've already read carefully (use a dedicated code-review skill)

---

## The flow

### 1. Prepare the question

Distill the ask into a single review brief:

```
TYPE: <architecture|security|strategy|plan|decision|code>
TOPIC: <one sentence>
ARTIFACTS: <file paths, diagram, plan>
WHAT I THINK: <your own first-pass take — the primary model's position>
WHAT I WANT VERIFIED: <1-3 specific questions>
```

If a file path was passed, read the file and embed the relevant portion in the brief. Don't rely on the second reviewer to read the filesystem — it typically runs in its own runtime, separate from your working directory.

### 2. Run the second reasoner

Invoke your second-model CLI as a subagent or direct shell call with the brief from step 1. For example, with the Codex CLI:

```
Agent(subagent_type: "<your second-model agent or CLI wrapper>", prompt: "<review brief from step 1>")
```

The point is genuine model-architecture independence — a different training distribution and different failure modes than the primary model, not just a second call to the same model.

**Default effort:** let the second model pick its own effort/reasoning level unless the review type is architecture or security, in which case ask for a higher setting explicitly in the brief.

**Read-only by default:** prepend `read-only — review only, do not edit` so the second reviewer doesn't touch files. You want its analysis, not its code.

### 3. Capture both positions

You already have the primary model's position from step 1 (`WHAT I THINK`). Capture the second model's output verbatim.

If the second model is unavailable or errors out:
- Try once to retry with a tightened prompt (cut the brief by 50%).
- If still failing, proceed with a single-model review and **explicitly label** the output as "Single-model review — second reasoner unavailable."

### 4. Synthesize

Produce the report:

```markdown
## Second Opinion — <type>

### Topic
<one sentence>

### Primary model's take
<your first-pass position from step 1, cleaned up>

### Second model's take
<verbatim, but trimmed to core arguments if verbose>

### Where they agree
- <point 1>
- <point 2>

### Where they disagree
| Point | Primary model | Second model | Who carries weight |
|---|---|---|---|
| <issue> | <position> | <position> | <primary / second / needs-human-judgment> |

### Critical issues flagged
- <any issue flagged critical by EITHER — err toward escalation>

### Recommended action
<one-paragraph synthesis, with explicit confidence level (high / medium / low)>

### Open questions for the user
- <only if the disagreement genuinely needs a human call>
```

### 5. Deliver

- If invoked standalone: present the report inline.
- If invoked inside a multi-phase pipeline with gates: return a PASS / REVISE / ESCALATE decision instead of (or alongside) the full report.
- If asked to save: write to `<workspace>/reports/second-opinion-<slug>-<YYYY-MM-DD>.md`.

---

## Heuristics

- **Treat the second model as a co-reviewer, not an oracle.** If it's confidently wrong, say so in the synthesis.
- **Agreement is not validation.** Two models can be wrong the same way. If both agree but you have doubt, escalate to the user.
- **Err toward critical.** If EITHER side flags a critical issue, surface it even if the other disagrees.
- **Short wins.** If both agree on the main question in one sentence, the report should be one sentence. Don't bloat.

## Error handling

- **Second-model CLI not installed or not authenticated:** run its setup step first (e.g. `codex --version` / login flow for Codex CLI), tell the user. Fall back to a single-model review and label it clearly.
- **Second model times out:** note "Second reasoner timed out — partial review." Proceed with whatever output exists.
- **File path doesn't exist:** report and stop; don't hallucinate content to review.

## Why this matters

Paper-architecture loops — where a single model convinces itself it's right — are a known failure mode of solo LLM reasoning. Bringing in a second model with a different training distribution is the cheapest structural defense against that loop: it costs one extra call, and it catches confident-but-wrong reasoning that a single model's self-review will not.
