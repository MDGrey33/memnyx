# Coordinated Integration Testing

A **core principle skill** that enforces comprehensive testing coordination for any system change in your infrastructure.

## Quick Summary

Before ANY system change:
1. **Identify** tool dependencies (MCP, hooks, services, configs)
2. **Check** what's actively running (don't disrupt critical work)
3. **Plan** testing across all 4 levels (unit → component → integration → system)
4. **Test** with real data and realistic conditions
5. **Document** results before declaring ready

## Why This Matters

Testing revealed **2 critical bugs** in the logging system that file inspection never would have caught:
- stdin consumption bug (hooks couldn't access response data)
- JSON parsing bug (status field was empty)

Both were fixed during testing, making production deployment clean.

**Without coordinated testing, these would have reached production.**

## The 4 Test Levels

| Level | What | Example |
|-------|------|---------|
| **1: Unit** | Individual component in isolation | Hook script execution |
| **2: Component** | Related systems together | Pre/post hooks + logbook writes |
| **3: Integration** | System with OTHER systems running | Hooks running while a background daemon is active |
| **4: System** | Full realistic conditions | Multiple agents + role switching + load |

## Time Allocation

- Building: 30-40%
- **Testing: 40-50%** (this is critical)
- Documentation: 10-20%

If testing takes less time than building, you're not testing thoroughly.

## When to Apply

**Automatically applied to:**
- Hooks and automation
- MCP integrations
- Configuration changes (settings.json, plist, etc.)
- Role-based routing or state management
- Workflow modifications

This is **non-optional** for any system change.

## Documentation

For full details, see `SKILL.md` in this directory.
