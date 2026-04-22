# ScrimBot User Guide

ScrimBot is a Discord bot for scrims, MRC match scheduling, Ignite result tracking, reminders, and upcoming schedule views. It creates Discord Scheduled Events, stores data per server, and shows Discord-native timestamps so every player sees local times in their own timezone.

## What The Bot Does

- Create scrim events against plain-text opponent names.
- Add, import, edit, view, archive, and delete MRC matches.
- Send 30-minute MRC reminders to a configured channel.
- Ping configured reminder roles.
- Show upcoming MRC matches and scrims.
- Track Ignite results from Liquipedia and auto-post new results.
- Keep settings independent per Discord server.
- Let configured manager roles operate the bot without full admin permissions.

## Install And Run

### Requirements

- Python 3.9 or newer
- A Discord bot token
- Bot permissions:
  - View Channels
  - Send Messages
  - Read Message History
  - Manage Events / Create Events
  - Use Application Commands

### Install

```bash
cd ScrimBot
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

### Configure Token

Copy the env template:

```bash
copy .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_actual_bot_token_here
GUILD_ID=0
```

`GUILD_ID=0` is fine. The bot syncs slash commands globally.

### Start The Bot

```bash
python main.py
```

Expected output:

```text
YourBotName has connected to Discord!
Synced X command(s)
```

## First-Time Server Setup

Run these commands in the Discord server where you want to use the bot.

### 1. Set Manager Roles

This lets staff manage the bot without needing full Discord admin permissions.

```text
/config manager_role role:@Tournament Staff
/config manager_role role:@MRC Admin
```

Check shared config:

```text
/config status
```

### 2. Set The Default Timezone

Use your main tournament timezone.

```text
/mrc config_timezone timezone_name:"America/Denver"
```

You can also use abbreviations like `EST`, `PST`, `UTC`, `MT`, or full IANA names like `Europe/London`.

### 3. Set The MRC Reminder Channel

```text
/mrc config_channel channel:#mrc-reminders
```

### 4. Add Reminder Ping Roles

```text
/mrc reminder_role_add role:@Players
/mrc reminder_role_add role:@MRC
```

List reminder roles:

```text
/mrc reminder_role_list
```

Scrim pings are configured separately:

```text
/scrim ping_role_add role:@Players
/scrim ping_role_add role:@Scrim Team
/scrim ping_role_list
```

### 5. Set Up Ignite Results

```text
/ignite set_channel channel:#ignite-results
/ignite set_source url:"https://liquipedia.net/marvelrivals/MR_Ignite/2026/Preseason/Americas"
```

Optional: only post results for one team.

```text
/ignite set_tracked_team team_name:"Vengeful"
```

Enable auto-posting:

```text
/ignite enable_auto
```

Check Ignite setup:

```text
/ignite status
```

### 6. Check Bot Health

```text
/health
```

This checks the database, background tasks, Ignite source reachability, and Discord latency.

## Common Workflows

### Schedule One Scrim

The team name is plain text. The opponent does not need a Discord role.

```text
/scrim create team_name:"Team1" event_datetime:"4/22/26 4pm EST" duration_hours:2
```

With a timezone override:

```text
/scrim create team_name:"Team1" event_datetime:"April 22 4:00 PM" duration_hours:2 timezone_name:"America/Denver"
```

The bot creates a Discord Scheduled Event with the required duration and stores the scrim for `/upcoming`.
The Discord event description includes the bot's `Event ID`, which is the number used for edit commands.

Edit a scrim later:

```text
/scrim edit event_id:12
```

Manage scrims like MRC events:

```text
/scrim view
/scrim upcoming days:14
/scrim status event_id:12 status:"Completed"
/scrim delete event_id:12
```

Set roles to ping when scrims are created:

```text
/scrim ping_role_add role:@Players
/scrim ping_role_add role:@Scrim Team
/scrim ping_role_list
```

### Add One MRC Event

```text
/mrc add datetime_str:"April 25 1:00 PM" rounds:"1-3" bracket:"Upper" duration_hours:2
```

With a timezone:

```text
/mrc add datetime_str:"April 25 1:00 PM" rounds:"Rounds 1-3" bracket:"Upper" duration_hours:2 timezone_name:"America/Denver"
```

### Bulk Import MRC Events

Use `/mrc import` with a required duration, then paste lines in this format:

```text
/mrc import schedule:"April 25 1:00 PM Rounds 1-3 Upper" duration_hours:2
```

```text
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Upper
April 25 7:00 PM Rounds 1-3 Lower
```

Lines can include a timezone:

```text
April 25 1:00 PM Rounds 1-3 Upper America/Denver
April 25 4:00 PM Rounds 1-3 Lower PST
```

### Add MRC Events Interactively

```text
/mrc session duration_hours:2
```

Then send one line at a time:

```text
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Lower
done
```

Use `cancel` to stop.

### View The Schedule

```text
/mrc view
```

By default this hides completed, cancelled, and archived matches.

Show completed/cancelled:

```text
/mrc view include_completed:true
```

Show archived:

```text
/mrc view include_archived:true
```

Long schedules have Previous/Next buttons.

### View Upcoming Items

MRC matches only:

```text
/mrc upcoming days:14
```

MRC matches and scrims together:

```text
/upcoming days:14
```

### Edit An MRC Event

```text
/mrc edit event_id:12
```

Discord opens a prefilled form with:

- Date/Time
- Timezone
- Duration Hours
- Rounds
- Bracket

Submit the form to update the database and the linked Discord Scheduled Event.
Use `/mrc status` to change event status.
The linked Discord Scheduled Event description includes the bot's `Event ID`.

### Change Match Status

```text
/mrc status event_id:12 status:"In Progress"
/mrc status event_id:12 status:"Completed"
```

Supported statuses:

- `Scheduled`
- `Checked In`
- `In Progress`
- `Completed`
- `Cancelled`

### Archive Completed Matches

```text
/mrc archive_completed
```

This archives completed and cancelled matches so normal schedule views stay clean.

### Repair Missing Discord Events

If Discord Scheduled Events were deleted manually, recreate them:

```text
/mrc repair_events
```

Include completed/cancelled matches:

```text
/mrc repair_events include_completed:true
```

### Delete An MRC Event

```text
/mrc delete event_id:12
```

This deletes the database match and its linked Discord Scheduled Event.

### Manually Check Ignite

```text
/ignite check_now
```

This checks the configured Liquipedia page immediately and posts new results if auto-posting is enabled and a channel is configured.

## Timezones And Local Times

The bot stores scheduled times in UTC internally and displays:

- the scheduled/event timezone
- a Discord native timestamp
- a relative timestamp

Discord native timestamps render in each player's local timezone. A Denver player, a London player, and a Sydney player will each see the local timestamp in their own timezone.

Example output shape:

```text
Saturday, April 25, 2026 at 01:00 PM MDT
Local: <t:1777143600:F> (<t:1777143600:R>)
```

In Discord, the `<t:...>` parts render as real local times.

## Command Reference

### Shared Config

| Command | What It Does |
| --- | --- |
| `/config manager_role role:@Role` | Adds a role allowed to manage bot commands. |
| `/config remove_manager_role role:@Role` | Removes one configured manager role. |
| `/config clear_manager_role` | Clears all configured manager roles. |
| `/config manager_roles` | Lists configured manager roles. |
| `/config status` | Shows shared config for the server. |
| `/health` | Checks database, task, Ignite, and latency health. |

### Scrims

| Command | What It Does |
| --- | --- |
| `/scrim create team_name event_datetime duration_hours` | Creates a scrim Scheduled Event against a plain-text opponent. |
| `/scrim view` | Shows active scrim events with pagination. |
| `/scrim upcoming` | Shows upcoming scrim events. |
| `/scrim edit event_id` | Opens a prefilled edit form for a scrim event. |
| `/scrim status event_id status` | Sets scrim event status. |
| `/scrim archive_completed` | Archives completed/cancelled scrim events. |
| `/scrim repair_events` | Recreates missing Discord Scheduled Events for scrims. |
| `/scrim delete event_id` | Deletes a scrim and its linked event. |
| `/scrim ping_role_add role:@Role` | Adds a role to ping when scrims are created. |
| `/scrim ping_role_remove role:@Role` | Removes a scrim ping role. |
| `/scrim ping_role_list` | Lists scrim ping roles. |
| `/upcoming days:14` | Shows upcoming MRC matches and scrims together. |

### MRC Scheduling

| Command | What It Does |
| --- | --- |
| `/mrc add` | Adds one MRC match with a required event duration. |
| `/mrc import` | Bulk imports many MRC matches from pasted text with one required duration for all imported events. |
| `/mrc session` | Adds matches one by one in chat with one required duration for the session. |
| `/mrc view` | Shows active MRC matches with pagination. |
| `/mrc upcoming` | Shows upcoming MRC matches. |
| `/mrc edit event_id` | Opens a prefilled edit form. |
| `/mrc status` | Sets match status. |
| `/mrc archive_completed` | Archives completed/cancelled matches. |
| `/mrc repair_events` | Recreates missing Discord Scheduled Events. |
| `/mrc delete` | Deletes a match and its linked event. |

### MRC Settings

| Command | What It Does |
| --- | --- |
| `/mrc config_view` | Shows MRC settings. |
| `/mrc config_channel channel:#channel` | Sets the MRC reminder channel. |
| `/mrc config_timezone timezone_name:"America/Denver"` | Sets default timezone. |
| `/mrc reminder_role_add role:@Role` | Adds a role to ping in reminders. |
| `/mrc reminder_role_remove role:@Role` | Removes a reminder ping role. |
| `/mrc reminder_role_list` | Lists reminder ping roles. |

### Ignite

| Command | What It Does |
| --- | --- |
| `/ignite set_channel channel:#channel` | Sets where Ignite results are posted. |
| `/ignite set_source url:"https://liquipedia.net/..."` | Sets the Liquipedia source page. |
| `/ignite enable_auto` | Enables auto result posting. |
| `/ignite disable_auto` | Disables auto result posting. |
| `/ignite status` | Shows Ignite settings and failure state. |
| `/ignite set_tracked_team team_name:"Vengeful"` | Only posts results involving that team. |
| `/ignite clear_tracked_team` | Posts results for all teams. |
| `/ignite check_now` | Checks Liquipedia immediately. |

## Permissions

Users can manage schedule/config commands if they have any of:

- Administrator
- Manage Server
- Manage Events
- any configured manager role from `/config manager_role`

The bot itself needs:

- View Channels
- Send Messages
- Read Message History
- Manage Events / Create Events
- Use Application Commands

## Per-Server Behavior

All main data is separated by Discord server:

- MRC matches
- scrims
- reminder channels
- reminder roles
- manager roles
- default timezone
- Ignite channel
- Ignite source URL
- Ignite tracked team
- Ignite posted-result history

Changes in one server do not affect another server.

## Troubleshooting

### Slash Commands Do Not Show Up

- Restart the bot.
- Wait a minute or two.
- Check the console for `Synced X command(s)`.
- Make sure the bot was invited with the `applications.commands` scope.

### Bot Cannot Create Events

- Give the bot Manage Events / Create Events permissions.
- Make sure the bot role is high enough in the server role hierarchy.

### MRC Import Fails

Use this format:

```text
April 25 1:00 PM Rounds 1-3 Upper
```

Required:

- month name
- day
- 12-hour time with AM/PM
- `Rounds X-X`
- `Upper` or `Lower`

### Scrim Pings Do Not Happen

Add at least one scrim ping role:

```text
/scrim ping_role_add role:@Players
```

### Ignite Does Not Post

Check:

```text
/ignite status
/health
```

Make sure:

- auto-posting is enabled
- a channel is set
- the source URL is reachable
- tracked team is not filtering out all results

### First Ignite Run Posts Old Results

The bot posts anything not already stored in its database. On a new database, existing Liquipedia results may be treated as new. To avoid this in the future, add a baseline command that marks current results as seen without posting.

## Files

```text
ScrimBot/
|-- main.py
|-- cogs/
|   |-- config.py
|   |-- health.py
|   |-- ignite.py
|   |-- mrc.py
|   |-- scrim.py
|   `-- upcoming.py
|-- models/
|   |-- database.py
|   |-- permissions.py
|   `-- time_utils.py
|-- tests/
|   `-- test_core.py
|-- requirements.txt
|-- .env.example
|-- .gitignore
`-- README.md
```

`bot_data.db` is created automatically when the bot runs.

## Run Tests

```bash
python -m unittest discover -s tests
```

## Notes For Operators

- Back up `bot_data.db` if the bot becomes important for multiple servers.
- Use `/health` after changing Ignite source URLs.
- Use `/mrc archive_completed` regularly to keep schedule views clean.
- Use `/mrc repair_events` if someone manually deletes Discord Scheduled Events.
