---
name: run-until-done
description: Autonomous task loop — runs a task repeatedly until completion criteria are met. No babysitting required.
user_invocable: true
---

## Model Selection

See `_shared/MODEL_SELECTION.md` (or your workspace's model-policy doc) for full policy.

- **Default model:** a small/fast tier (e.g. Haiku-class) — loop controller reads state → decides stop/continue → invokes — structured
- **Promote to a mid-tier reasoning model when:** the loop task itself needs reasoning — but that's the inner task, not this controller
- **Promote to a top-tier model when:** never

# Run Until Done (Ralph Loop)

Execute a multi-step task autonomously, looping until done. No human check-ins mid-execution.

## Usage

Invoke with: `/run-until-done`

You will be asked for:
1. **Task description** — what to accomplish
2. **Completion criteria** — how to know it's done (e.g., "all 19 items scored", "5 outreach messages written")
3. **Max iterations** — safety limit (default: 10)
4. **Output location** — where to drop results (default: `<workspace>/inbox/`)

## Execution Loop

```
LOOP until (done OR iterations exhausted):
  1. ASSESS — What's the current state? What's been done? What remains?
  2. PLAN — What's the single next action to make progress?
  3. EXECUTE — Do it. Use tools. Write files. Run commands.
  4. VERIFY — Did it work? Check output, confirm file written, validate result.
  5. CHECK COMPLETION — Do results meet the completion criteria?
     - YES → DONE, write summary, notify
     - NO, iterations remain → continue loop
     - NO, limit hit → write partial results + status, notify
```

## Rules

- Never ask the user mid-loop. Make reasonable decisions autonomously.
- If genuinely blocked (missing credential, ambiguous requirement), write the blocker to the output file and stop gracefully — don't loop forever on a dead end.
- Each iteration must make measurable progress. If two consecutive iterations produce identical state, stop and report the blockage.
- All intermediate state goes to `<workspace>/memory/loop-state.md` — so if the session compacts, the next session can resume.
- Final output always goes to `<workspace>/inbox/` with a clear filename.

## Loop State File Format

Write to `<workspace>/memory/loop-state.md` after each iteration:

```markdown
# Loop State
Task: [task description]
Started: [timestamp]
Iteration: [N] of [max]
Status: in-progress | done | blocked

## Completed
- [item 1]
- [item 2]

## Remaining
- [item 3]
- [item 4]

## Last Action
[what was just done]

## Next Action
[what the next iteration will do]

## Blocker (if any)
[description of what's blocking progress]
```

## Completion Output

When done, write to `<workspace>/inbox/[task-slug]-results.md`:

```markdown
# [Task] — Complete
Date: [timestamp]
Iterations used: [N] of [max]

## Results
[actual output]

## Summary
[one-paragraph summary for the user]
```

Then output to the conversation:
```
✅ Done. [task] complete in [N] iterations.
Results: <workspace>/inbox/[filename]
```

## Resuming After Compaction

If context compacts mid-loop, on the next session:
1. Read `<workspace>/memory/loop-state.md`
2. Check status — if `in-progress`, resume from "Next Action"
3. Continue the loop from where it left off
