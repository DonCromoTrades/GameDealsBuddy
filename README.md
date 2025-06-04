# GameDealsBuddy

GameDealsBuddy searches for discounted games on the Steam and Epic Games stores.
It can post game deals to a Discord channel with a brief AI-generated summary and rating information.

## Setup

1. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
   (The `openai` package is optional but included for convenience.)

2. Set the following environment variables:
   - `DISCORD_WEBHOOK_URL` – Discord webhook URL for the channel to post deals.
   - `OPENAI_API_KEY` – API key for OpenAI (optional). If not provided, a simple summary is used.
   - `CHECK_INTERVAL_HOURS` – How often to check for new deals (default: `8`).
   - `POSTED_DEALS_FILE` – File path for storing already posted deal IDs (default: `posted_deals.json`).
   - `RESET_CACHE_ON_STARTUP` – If set to `true`, clears the posted deals cache when the bot starts.
   - `CACHE_RESET_HOURS` – Interval in hours to automatically reset the cache (optional).

## Running

Execute the bot with Python:

```bash
python bot.py
```

The script will continuously run, checking for deals at the configured interval and posting messages to Discord.

Deals are reported when a game is free or discounted by at least 50%.
