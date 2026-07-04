# More Than Scaling Discord Bot

A Discord.py bot that verifies membership by email against GoHighLevel (GHL) contact tags and assigns roles accordingly.

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

4. In GHL, create a Private Integration Token (Settings → Private Integrations) with at least the `contacts.readonly` scope, and note the location/sub-account ID it belongs to.

5. Set `GHL_API_KEY`, `GHL_LOCATION_ID`, and `GHL_TAG_ROLES` (tag-to-role mapping) in `.env`.

6. Run the bot.

```powershell
python run.py
```

## Commands

- `/status` - Shows bot and server configuration status.
- `/set_backlog_channel channel:<channel>` - Admin-only: sets the channel where verification attempts are logged.
- `/ghl_lookup email:<email>` - Admin-only: fetches and displays a contact's raw GHL record by email (testing).
- `/sync` - Admin-only: globally syncs slash commands.

## Verification Flow

Members click the Verify button posted via `/setup_verification` and submit their email. The bot looks up that email in GHL:

- If the email isn't found, the member is told they're not a member and given a subscribe link.
- If the contact has none of the tags configured in `GHL_TAG_ROLES`, the member is told there's no active subscription.
- If a tag matches, the mapped role (plus `VERIFIED_ROLE_ID`, if set) is assigned, and the verified email is stored locally (`data/verified-members.json`) against their Discord ID.

Every 6 hours, a background task rechecks every member holding a tag-mapped role against their current GHL tags, and removes the role if the tag is no longer present.

## Adding a New Subscription Tag

Add another `TagName:RoleID` entry to `GHL_TAG_ROLES` in `.env` — no code changes needed.

Activity logs (member join/leave, verification results, role removals) are sent to the channel configured with `/set_backlog_channel`. Channel selection is saved locally in `data/bot-state.json`.
