# Architecture & Implementation Details

## Overview

FoodAgend is a single long-running Python `asyncio` process with six subsystems coordinated by a central state machine. There is no web framework, no ORM, and no external message queue — just a polling loop, SQLite, and AppleScript.

```
Scheduler (APScheduler)  -->  Orchestrator (state machine)
                                 |         |          |
                           iMessage    Meal Planner   Picnic
                           Handler    (Claude API)    Cart Filler
                              |            |
                         chat.db +     Preference
                         AppleScript    Engine (SQLite)
```

## State machine

The orchestrator drives a session through these states:

```
IDLE
  |  (parent sends trigger phrase, or cron fires)
  v
COLLECTING_PREFERENCES  ──(timeout: 4h)──┐
  |                                       |
  |  (all members responded, or parent    |
  |   says "go ahead")                    |
  v                                       v
GENERATING_PLAN
  |
  v
AWAITING_APPROVAL
  |  ├── "ok"             --> COMPILING_INGREDIENTS
  |  ├── change request   --> revise, stay in AWAITING_APPROVAL
  |  └── "nee"            --> regenerate, back to GENERATING_PLAN
  v
COMPILING_INGREDIENTS
  |
  v
CHECKING_PANTRY  ──(timeout: 2h)──┐
  |                                |
  v                                v
FILLING_CART
  |
  v
COMPLETED
```

State transitions are persisted to SQLite so the agent can resume after a crash or restart. Transient data (collected wishes, which members responded) is held in memory only — a restart during preference collection will wait for new responses.

## iMessage I/O

### Reading messages

The agent polls `~/Library/Messages/chat.db` (a SQLite database maintained by Messages.app) every 5 seconds. It tracks its position via `ROWID` — only messages with a ROWID higher than the last processed one are fetched.

Key implementation details:

- **Apple epoch**: Message timestamps use Core Data's epoch (2001-01-01), offset by 978307200 seconds from Unix epoch. The timestamp is stored in nanoseconds.
- **attributedBody parsing**: On macOS Ventura+, the `text` column is often NULL and the content lives in `attributedBody` as a serialized `NSAttributedString`. The reader extracts text by finding the `\x01\x2B` marker followed by a length byte and UTF-8 text. A regex fallback handles edge cases.
- **Own-message skipping**: After sending a message, the handler waits 500ms for Messages.app to write it to chat.db, then advances the ROWID cursor past the outgoing message to avoid re-processing.

### Sending messages

Messages are sent via AppleScript (`osascript`) calling Messages.app's scripting interface. Special characters are escaped for AppleScript string literals. Each send runs as an async subprocess with a 30-second timeout.

### Permissions

Reading chat.db requires **Full Disk Access** for the running process. Sending requires **Automation** permission for Messages.app, which macOS prompts for on first use.

## Claude API usage

The agent uses different Claude models for different tasks based on the complexity/speed tradeoff:

| Task | Model | Temperature | Why |
|---|---|---|---|
| Meal plan generation | Sonnet | 0.7 | Creative variety in recipes |
| Plan revision | Sonnet | 0.7 | Needs to understand context and make targeted changes |
| Conversational replies | Sonnet | 0.7 | Natural tone |
| Message classification | Haiku | 0 | Fast, deterministic intent detection |
| Preference extraction | Haiku | 0 | Structured JSON output |
| Search term generation | Haiku | 0 | Simple translation task |
| Product match selection | Haiku | 0 | Structured comparison |
| Pantry item matching | Haiku | 0 | Fuzzy matching, fast |

All Claude interactions use a single prompt (no multi-turn) and expect JSON responses. The `parse_json_response` utility strips markdown code fences if Claude includes them.

### Prompt design

Prompts are centralized in `conversation/prompts.py`. Key design choices:

- **Structured JSON output**: Every prompt specifies the exact JSON schema expected. This avoids parsing ambiguity.
- **Dutch ingredient names**: The meal plan generation prompt explicitly requests Dutch names for ingredients, since they'll be used for Picnic search queries.
- **Revision with full context**: The plan revision prompt receives the complete current plan as JSON (all recipes with ingredients and instructions), not just summaries. This ensures Claude can preserve unchanged meals exactly.

## Preference system

Preferences are extracted from every incoming message (even outside active sessions) using Claude Haiku. Each preference has:

- **Category**: likes, dislikes, allergy, dietary, cuisine_preference, general
- **Confidence score**: 0.0–1.0, increases by 0.1 each time a preference is confirmed
- **Deduplication**: Before storing, existing preferences are checked for substring matches in the same category. Matches bump the confidence instead of creating duplicates.

Preferences accumulate over time and are included in every meal plan generation prompt, giving the agent a growing understanding of the family's tastes.

## Picnic integration

### Authentication

The agent uses the `python-picnic-api2` library, which handles Picnic's auth token rotation transparently. Picnic rotates the `x-picnic-auth` header on every API response — the library's `requests.Session` captures and reuses the refreshed token automatically.

### Cart filling pipeline

For each ingredient that isn't already available at home:

1. **Generate search terms** — Claude Haiku translates the Dutch ingredient name into 2-3 supermarket search queries
2. **Search Picnic** — Each term is tried in order; the first one that returns results is used
3. **Select best match** — Claude Haiku compares the recipe's needs against the top 15 Picnic products, picking the best match by name, quantity, and price
4. **Add to cart** — The selected product is added with the right count (e.g., if 400g is needed and packs are 300g, count=2)

Before searching, duplicate ingredients across recipes are merged (summing quantities for the same ingredient and unit).

### Pantry matching

When the parent says what they already have at home ("I got rice, olive oil, and the spices"), the agent uses Claude Haiku to fuzzy-match their free-text response against the ingredient list. This handles:

- English names for Dutch ingredients ("olive oil" = "olijfolie")
- Abbreviations and informal names
- General terms covering specific items ("oil" covers both "olijfolie" and "zonnebloemolie")

Matched ingredients are marked as `already_available` and skipped during cart filling.

## Database

SQLite with WAL mode and foreign keys enabled. No ORM — direct `sqlite3` with parameterized queries.

### Schema

| Table | Purpose |
|---|---|
| `family_members` | Name, iMessage ID, role (parent/child) |
| `preferences` | Per-member food preferences with confidence scores |
| `meal_plan_sessions` | State machine state, date range |
| `recipes` | Generated recipes linked to sessions |
| `recipe_ingredients` | Ingredients with Picnic match status |
| `conversation_log` | Full message history (incoming + outgoing) |
| `meal_history` | Past meals for variety tracking |
| `agent_state` | Key-value store (last processed ROWID, etc.) |

Family members are synced from `config.toml` on every startup. The database is created automatically if it doesn't exist.

## Configuration

Configuration is loaded from TOML (`config.toml`) with Pydantic validation. Secrets come from environment variables, loaded from `.env` if present.

The config is resolved in this order:
1. Path passed as CLI argument
2. `FOODAGEND_CONFIG` environment variable
3. `config.toml` in the current directory

## Scheduling

APScheduler's `AsyncIOScheduler` with a cron trigger can automatically start a planning session on a configured day and time (e.g., Sunday 10:00). Disabled by default — most users trigger sessions manually via iMessage.

## Bilingual support

The agent supports English and Dutch, configured via `agent.language` in config. All user-facing messages have both translations defined in `orchestrator.py`. Claude prompts specify the response language, and the agent matches the family member's language when they write in a different one.

## Error handling and resilience

- **Session recovery**: Active sessions are persisted to SQLite and resumed on restart
- **Message ROWID tracking**: Stored in `agent_state` table, survives restarts
- **Graceful shutdown**: SIGINT/SIGTERM are caught and trigger a clean shutdown of the scheduler and polling loop
- **LaunchAgent**: The `install_launchd.sh` script sets `KeepAlive=true` so macOS restarts the agent after crashes
- **Cart fill errors**: Individual product failures don't abort the entire cart fill — errors are collected and reported to the parent

## Dependencies

| Package | Purpose |
|---|---|
| `anthropic` | Claude API SDK |
| `python-picnic-api2` | Picnic supermarket API client |
| `apscheduler` | In-process cron scheduling |
| `pydantic` | Config validation |

No web framework. No external database. No container runtime. The agent is a single Python process that reads a SQLite file and calls two APIs.
