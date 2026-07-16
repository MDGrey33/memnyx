---
name: coordinated-integration-testing
description: Enforce coordinated integration testing — identify tool dependencies, check running systems, test all 4 levels (unit/component/integration/system), never disrupt workflows
user_invocable: false
category: core-principle
priority: critical
---

## Model Selection

See `~/.claude/skills/_shared/MODEL_SELECTION.md` for full policy.

- **Default model:** Sonnet 4.6 — dependency analysis and test sequencing across tools needs judgment about side effects
- **Promote to Opus when:** architectural decision about test ordering for a system redesign

# Coordinated Integration Testing

A **CORE PRINCIPLE SKILL** that enforces comprehensive testing across the user's machine or workspace.

## When This Applies

**EVERY system change that involves:**
- Hooks or automation
- Integration with multiple tools (MCP, scheduled tasks, agents)
- Changes to configuration (settings.json, plist, etc.)
- Modifications to existing workflows

This is **NON-OPTIONAL**. Testing is more critical than the system buildup itself.

---

## The Testing Coordination Protocol

### Phase 1: Dependency Analysis (Before Build)

Identify all integration points:

```
Questions to answer BEFORE starting:
- What MCP servers does this touch?
- What existing hooks might conflict?
- What configuration files are affected?
- What running services might be disrupted?
- What workflows are impacted?
```

**Example for logging system:**
- MCP: None
- Existing hooks: checkpoint, gap-tracker, activity-tracker, log-tool-before/after
- Config: settings.json
- Services: background daemon, and any subagents that read the affected logs

### Phase 2: Running-System Check (Before Testing)

Check what's actively running before testing:

```bash
pgrep -af "<your-daemon-name>"          # background daemons
launchctl list | grep -i <your-daemon-name>   # launchagents (macOS)
lsof | grep <workspace>                  # active file handles
tail <workspace>/log/tool-events.jsonl   # recent activity, if you keep one
```

If a daemon is mid-task, wait or coordinate. Don't restart something while it's writing.

### Phase 3: Test Level Planning

All systems must pass all 4 test levels:

| Level | Scope | Examples |
|---|---|---|
| **1: Unit** | Individual components in isolation | Hook script, JSON parsing |
| **2: Component** | Related systems working together | Pre/post hooks together, log file writes |
| **3: Integration** | System interacting with OTHER systems | Settings.json valid while bridge running, hooks don't conflict |
| **4: System** | Full system under realistic conditions | Multiple agents + logging under load |

**Mistake pattern:** Testing only Levels 1-2, assuming 3-4 will work. They often don't.

### Phase 4: Coordinated Test Execution

Create and execute test plan:

```markdown
# Test Plan: [System Name]

## Integration Points
- MCP Servers: [list and how they're touched]
- Existing Hooks: [list and potential conflicts]
- Config Files: [what changes]
- Services: [what's running, what might break]

## Running Systems
- Active daemons: [from pgrep/launchctl]
- Safe window: [when to test]
- Duration: [how long]
- Disruptive: [yes/no]

## Test Levels
- [ ] Level 1: Unit (isolated)
- [ ] Level 2: Component (related)
- [ ] Level 3: Integration (with other systems)
- [ ] Level 4: System (realistic load)

## Rollback Plan
If X breaks, recovery is: [steps]

## Results
[Document pass/fail for each level]
```

### Phase 5: Documentation & Reporting

Before declaring system "ready":

1. **Test Results File** — comprehensive results document
   - What passed (all 4 levels)
   - What failed (bugs found)
   - Fixes applied
   - Final verdict
2. **Memory Capture** — if lessons learned, log to memory
   - What patterns to enforce
   - What to avoid next time
   - Integration insights

---

## Common Mistakes (DON'T DO THESE)

| ❌ Wrong | ✅ Right |
|---|---|
| Test only file existence | Execute code with real data |
| Skip running-system check | Always check daemons/launchagents first |
| Test Level 1-2 only | Test all 4 levels |
| Assume no conflicts | Explicitly test integration |
| Test in isolation | Test while other systems run |
| No rollback plan | Document recovery before starting |
| No test results doc | Always document results |

---

## Implementation Steps

When implementing ANY system change:

1. **STOP: Identify dependencies** — write down MCP servers, hooks, services, configs.
2. **CHECK: What's running** — pgrep + launchctl + lsof. If something critical is mid-task, wait.
3. **PLAN: Create test plan document** — integration points, running systems, test levels, rollback.
4. **BUILD: Implement system** — happens AFTER planning.
5. **TEST: Execute all 4 levels** — unit → component → integration → system.
6. **DOCUMENT: Results & findings** — test results file + memory capture.
7. **DELIVER: Only then declare ready** — not before testing is complete and documented.

---

## Testing is More Critical Than Building

Time allocation:

```
Building:  30-40%
Testing:   40-50%
Docs:      10-20%
```

If testing takes less time than building, you're not testing thoroughly enough.

---

## Real-World Example: Logging System

**What went wrong (first attempt):**
- ❌ Skipped Level 3-4 testing
- ❌ Didn't check what was running
- ❌ Assumed no hook conflicts
- ❌ Only verified file existence
- **Result:** Bugs found after deployment (stdin consumption, JSON parsing)

**What went right (after coordination):**
- ✅ Identified all integration points (5 existing hooks, settings.json)
- ✅ Checked what was running before testing
- ✅ Created comprehensive test plan
- ✅ Tested all 4 levels with real data
- ✅ Found and fixed 2 real bugs during testing
- ✅ Documented all results
- **Result:** Clean production deployment

---

## When to Use This Skill

NEVER user-invocable — it's a **core operating principle** that applies automatically:

- **Before any system change:** Apply Phase 1-2 (dependency analysis, running-system check)
- **During implementation:** Apply Phase 3-4 (test planning, execution)
- **Before delivery:** Apply Phase 5 (documentation)

---

## Coordination with Other Skills

- `lessons` — capture testing lessons learned
- `skills-manager` — review skills based on test findings
- `bye` — report testing results at session end
- `mcp-doctor` — check health of MCP servers before testing

**Unique responsibility:** owns the testing coordination protocol. No other skill can override it.

---

## Summary

- **Principle:** Testing is not optional; testing requires coordination to avoid disrupting running systems.
- **Protocol:** Dependency analysis → running-system check → test plan → execute 4 levels → document results → deliver.
- **Outcome:** Systems that actually work, not just systems that build.
