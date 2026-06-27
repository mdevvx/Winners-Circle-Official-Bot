# More Than Scaling Discord Bot

A Discord.py bot with slash commands and Google Sheets member status tracking.

## Setup

1. Create a virtual environment and install dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in the values.

3. In the Discord Developer Portal, enable these privileged intents:

- Server Members Intent
- Message Content Intent

4. Put your Google service account JSON at `credentials/google-service-account.json`, or update `GOOGLE_SERVICE_ACCOUNT_FILE_WC`.

5. Share the Google Sheet with the service account email.

6. Optional: set `VERIFIED_ROLE_ID` to the Discord role ID the bot should give to members found in the sheet.

7. Run the bot.

```powershell
python run.py
```

## Commands

- `/status` - Shows bot and server configuration status.
- `/set_log_channel channel:<channel>` - Admin-only command that sets the activity log channel.
- `/test_member member:<member>` - Admin-only flow test for a member's Google Sheet row.
- `mts!sync` - Globally syncs slash commands.

When a member joins or leaves, the bot updates their `Discord Status` in the configured Google Sheet. If `VERIFIED_ROLE_ID` is set, joining members found in the sheet also receive that role.

Activity logs are sent to the channel configured with `/set_log_channel`. The selected channel is saved locally in `data/bot-state.json`.

## Google Sheet Columns

The bot expects a Discord ID column. Accepted names are:

- `Discord ID`
- `DiscordID`
- `discord_id`
- `discord id`
- `Please provide your Discord ID (optional)`

If `Discord Status` does not exist, the bot creates it automatically.
