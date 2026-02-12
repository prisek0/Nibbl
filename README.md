# FoodAgend

AI-powered family dinner planning agent for macOS. Communicates with family members via iMessage, generates weekly meal plans using Claude, and fills your [Picnic](https://picnic.app/) shopping cart with the needed ingredients.

## How it works

1. A parent triggers planning by sending "plan dinner" (or "plan eten") via iMessage
2. The agent asks all family members for their dinner wishes
3. Claude generates a multi-day meal plan based on preferences, season, and recent history
4. The parent reviews and can request changes ("swap the dal for something else on Saturday")
5. The agent asks what pantry staples are already at home
6. Remaining ingredients are automatically searched and added to the Picnic cart

The agent runs as a persistent background process on macOS, polling for new iMessages every few seconds.

## Requirements

- **macOS** (Ventura 13+ recommended) with Messages.app configured
- **Python 3.11+**
- **Full Disk Access** for Terminal / your Python process (to read `~/Library/Messages/chat.db`)
- **Automation permission** for Messages.app (prompted on first run)
- An **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com/))
- A **Picnic** account (NL, DE, or BE)

## Setup

### 1. Clone and create virtualenv

```bash
git clone <repo-url> FoodAgend
cd FoodAgend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development (linting, tests):

```bash
pip install -e ".[dev]"
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
PICNIC_USERNAME=your@email.com
PICNIC_PASSWORD=your-picnic-password
```

These are loaded automatically when the agent starts.

### 3. Configure the agent

Copy and edit the config file:

```bash
cp config.toml config.example.toml  # keep a clean copy
```

Edit `config.toml` with your family details:

```toml
[agent]
poll_interval_seconds = 5
plan_days = 4              # number of dinner days to plan
language = "en"            # "en" or "nl" — agent speaks this language

[family]
[[family.members]]
name = "Alice"
imessage_id = "+31612345678"   # phone number or Apple ID email
role = "parent"

[[family.members]]
name = "Bob"
imessage_id = "+31698765432"
role = "parent"

[[family.members]]
name = "Charlie"
imessage_id = "+31611111111"
role = "child"

[imessage]
self_id = "+31612345678"   # your own number (the Mac owner)

[picnic]
country_code = "NL"        # NL, DE, or BE

[schedule]
enabled = false            # set to true for automatic weekly triggers
day_of_week = "sun"
hour = 10
minute = 0
```

### 4. Grant macOS permissions

**Full Disk Access** — required to read the Messages database:
- System Settings > Privacy & Security > Full Disk Access
- Add Terminal.app (or your terminal emulator / IDE)

**Automation** — required to send iMessages:
- Granted automatically on first run when the agent sends its first message
- Messages.app must be running (background is fine)

### 5. Run the agent

```bash
# From the project directory, with the venv activated:
python -m src.main

# Or with a custom config path:
python -m src.main /path/to/config.toml
```

The agent logs to both the console and `logs/foodagend.log`.

Stop it with `Ctrl+C`.

## Running as a background service

To have FoodAgend start automatically on login and restart on crashes:

```bash
bash scripts/install_launchd.sh
launchctl load ~/Library/LaunchAgents/com.foodagend.agent.plist
```

To stop and uninstall:

```bash
launchctl unload ~/Library/LaunchAgents/com.foodagend.agent.plist
bash scripts/uninstall_launchd.sh
```

Logs are written to `logs/stdout.log` and `logs/stderr.log` when running via launchd.

## Usage

### Trigger phrases

Send any of these via iMessage to start a planning session:

- "plan dinner" / "plan eten"
- "wat eten we" / "what's for dinner"
- "boodschappen" / "weekmenu"
- "meal plan" / "start planning"

### During a session

| Phase | What happens | Your options |
|---|---|---|
| **Preferences** | Agent asks everyone for wishes | Send food preferences, dietary needs, or specific requests |
| **Plan review** | Agent presents the meal plan | "ok" to approve, describe changes, or "nee" to regenerate entirely |
| **Pantry check** | Agent lists pantry staples | Tell it what you already have at home (free text, any language) |
| **Cart filling** | Agent searches Picnic and fills cart | Wait for the report, then check the Picnic app |

Send "stop" or "cancel" at any point to abort the session.

### Preferences

The agent learns preferences over time. Things like "I don't like fish" or "keep it vegetarian" are stored with confidence scores and influence future plans. Preferences are extracted from every message, even outside active sessions.

## Fresh start

To reset all data (preferences, history, sessions):

```bash
rm data/foodagend.db*
```

The database is recreated automatically on next startup.

## Project structure

```
src/
  main.py                    # Entry point, wiring, asyncio loop
  config.py                  # TOML + .env loading via Pydantic
  models.py                  # Dataclasses and enums
  database.py                # SQLite persistence
  orchestrator.py            # Central state machine
  utils.py                   # JSON parsing helpers
  imessage/
    reader.py                # Poll chat.db for new messages
    sender.py                # Send via AppleScript
    handler.py               # Combines reader + sender
  conversation/
    manager.py               # Message routing and classification
    prompts.py               # All Claude prompt templates
  planner/
    meal_planner.py          # Meal plan generation and revision
    preference_engine.py     # Preference extraction and storage
    pantry_matcher.py        # Fuzzy pantry item matching
    formatter.py             # Format plans/lists for iMessage
  picnic/
    client.py                # Thin wrapper around python-picnic-api2
    cart_filler.py           # Search, match, and add products to cart
  scheduler.py               # APScheduler weekly trigger
scripts/
  install_launchd.sh         # Install macOS LaunchAgent
  uninstall_launchd.sh       # Remove macOS LaunchAgent
config.toml                  # Your configuration (git-ignored)
.env                         # API keys and passwords (git-ignored)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for design details and implementation choices.
