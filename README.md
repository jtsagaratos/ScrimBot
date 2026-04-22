# ScrimBot User Guide

ScrimBot helps Discord communities schedule scrims, MRC matches, tournaments, reminders, and Ignite result posts. It creates Discord Scheduled Events, keeps each server's settings separate, and uses Discord timestamps so players see times in their own local timezone.

## What ScrimBot Does

- Creates Discord Scheduled Events for scrims, MRC matches, and tournaments.
- Posts new events into the channels you choose during setup.
- Sends reminder pings before events using your selected reminder lead time.
- Lets you choose reminder roles once for MRC, scrims, and tournaments.
- Tracks event status: Scheduled, Checked In, In Progress, Completed, or Cancelled.
- Shows private schedule views so commands do not clutter public channels.
- Edits MRC, scrim, and tournament events from one shared `/edit` command.
- Tracks Ignite results from Liquipedia and posts new results automatically.
- Keeps settings and schedules independent per Discord server.

## Quick Start

### 1. Install Python Dependencies

Use Python 3.9 or newer.

```bash
python -m pip install -r requirements.txt
```

### 2. Add Your Discord Token

Copy the example environment file:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Open `.env` and add your token:

```env
DISCORD_TOKEN=your_actual_bot_token_here
GUILD_ID=0
```

For testing, set `GUILD_ID` to your Discord server ID. This makes slash command updates appear much faster. If `GUILD_ID=0`, Discord may take longer to show new global slash commands.

### 3. Start The Bot

```bash
python main.py
```

You should see something like:

```text
MRC Bot#6950 has connected to Discord!
Synced X command(s)
```

### 4. Run Setup In Discord

In your server, run:

```text
/setup
```

Use this setup panel to configure the bot. Most bot settings live here so admins do not need to remember many setup commands.

## Bot Permissions

When inviting the bot, give it:

- View Channels
- Send Messages
- Read Message History
- Manage Events or Create Events
- Use Application Commands

Invite it with the `bot` and `applications.commands` scopes.

## First-Time Setup

Run `/setup`, then work through these sections.

### Timezone

Set the server's default timezone. This is used when a command does not include a timezone.

Examples:

```text
America/Denver
America/New_York
Europe/London
UTC
EST
PST
```

### Roles

Use the Roles page to configure:

- Manager Roles: people who can create, edit, delete, archive, and configure events.
- Reminder Roles: roles that get pinged for MRC, scrim, and tournament reminders.
- Reminder Lead Time: choose 15 minutes, 30 minutes, 45 minutes, or 1 hour.

The role menus use checkmarks. Check a role to add it, uncheck it to remove it.

### Channels

Use the Channels page to choose:

- Reminder Channel: where MRC, scrim, and tournament reminders are sent.
- MRC Event Channel: where new MRC event posts go.
- Scrim Event Channel: where new scrim event posts go.
- Tournament Event Channel: where new tournament event posts go.

Command confirmations are private to the user who ran the command. The public channels only receive the actual event posts and reminder pings.

### Ignite

Use the Ignite page to choose:

- Ignite Results Channel
- Liquipedia source URL
- Optional tracked team filter
- Auto-post on or off

If a tracked team is set, the bot only posts Ignite results where that team appears.

## Daily Commands

### Create A Scrim

Use `/scrims create`.

```text
/scrims create team:"Vengeful" date_time:"4/22/26 4pm EST" duration_hrs:2
```

With an explicit timezone:

```text
/scrims create team:"Vengeful" date_time:"April 22 4:00 PM" duration_hrs:2 timezone:"America/Denver"
```

Scrim Event IDs start with `S`, such as `S1`.

### Create A Tournament

Use `/tournaments create`.

```text
/tournaments create name:"Ignite Qualifier" date_time:"4/24/26 6pm EST" duration_hrs:3
```

Tournament Event IDs start with `T`, such as `T1`.

### Add One MRC Event

Use `/mrc add`.

```text
/mrc add season:7 duration_hrs:2 date_time:"April 25 1:00 PM" name:"Rounds 1-3"
```

Numeric dates and timezone abbreviations also work:

```text
/mrc add season:7 duration_hrs:2 date_time:"4/20/26 3PM EST" name:"Rounds 7-9"
```

MRC Event IDs start with `M`, such as `M1`.

### Add Multiple MRC Events In A Session

Use `/mrc session` when you want to type several MRC dates one at a time.

```text
/mrc session season:7 duration_hrs:2
```

Then type one event per message:

```text
April 25 1:00 PM Rounds 1-3
4/20/26 3PM EST Rounds 7-9
April 25 4:00 PM Rounds 1-3 Upper
done
```

Use `cancel` to stop without continuing. The setup/instruction messages are private, and the bot tries to clean up the schedule lines you typed when the session ends.

### Bulk Import MRC Events

Use `/mrc import` for a pasted schedule.

```text
/mrc import schedule:"April 25 1:00 PM Rounds 1-3 Upper" duration_hrs:2
```

The pasted schedule can contain multiple lines:

```text
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 4-6 Upper
April 25 7:00 PM Rounds 7-9
April 26 6:00 PM Grand Finals
```

The final `Upper` or `Lower` is optional.

## Viewing Schedules

These commands are private to the user who runs them.

```text
/mrc view
/scrims view
/tournaments view
/upcoming days:14
```

Use upcoming commands for one event type:

```text
/mrc upcoming days:14
/scrims upcoming days:14
/tournaments upcoming days:14
```

Use the shared upcoming command to see MRC, scrims, and tournaments together:

```text
/upcoming days:14
```

Schedule views show the event title first and place the Event ID at the bottom.

## Editing Events

Use one shared command for everything:

```text
/edit event_id:M1
/edit event_id:S1
/edit event_id:T1
```

The letter tells the bot what kind of event to edit:

- `M` means MRC
- `S` means scrim
- `T` means tournament

Discord opens a form with the current event details. Submit the form to update both the database and the linked Discord Scheduled Event.

## Changing Status

Set status with the matching command group:

```text
/mrc status event_id:M1 status:"Completed"
/scrims status event_id:S1 status:"In Progress"
/tournaments status event_id:T1 status:"Cancelled"
```

Supported statuses:

- Scheduled
- Checked In
- In Progress
- Completed
- Cancelled

## Deleting Events

Delete commands remove both the bot database entry and the linked Discord Scheduled Event.

```text
/mrc delete event_id:M1
/scrims delete event_id:S1
/tournaments delete event_id:T1
```

## Archiving Completed Events

Archive completed or cancelled events to keep normal views clean.

```text
/mrc archive_completed
/scrims archive_completed
/tournaments archive_completed
```

Archived events stay in the database, but normal views hide them unless you ask to include archived events.

## Repairing Discord Scheduled Events

Use repair commands if someone manually deletes a Discord Scheduled Event but the bot still has it in the database.

```text
/mrc repair_events
/scrims repair_events
/tournaments repair_events
```

## Ignite Result Tracking

Ignite setup is inside `/setup` under the Ignite section.

After setup, you can manually check Liquipedia:

```text
/ignite check_now
```

When auto-posting is enabled, the bot checks the configured Liquipedia source every few minutes and posts new results to the Ignite Results Channel. It avoids duplicate posts using stored match keys.

## Timezones

The bot stores times in UTC internally and displays Discord native timestamps. That means each player sees the time in their own Discord-local timezone.

Example:

```text
Time: Wednesday, April 22, 2026 at 10:00 PM EDT
Local: Wednesday, April 22, 2026 8:00 PM (in a day)
```

Players in other regions will see the local timestamp converted for them by Discord.

## Command Reference

### Setup And Health

| Command | What It Does |
| --- | --- |
| `/setup` | Opens the setup panel for timezone, roles, channels, reminders, and Ignite. |
| `/health` | Checks database, background tasks, Ignite source status, and latency. |
| `/upcoming days` | Shows upcoming MRC, scrim, and tournament events together. |
| `/edit event_id` | Opens the edit form for `M#`, `S#`, or `T#` events. |

### MRC

| Command | What It Does |
| --- | --- |
| `/mrc add` | Adds one MRC event. |
| `/mrc import` | Bulk imports multiple MRC events from pasted text. |
| `/mrc session` | Starts an interactive MRC entry session. |
| `/mrc view` | Shows MRC events with pagination. |
| `/mrc upcoming` | Shows upcoming MRC events. |
| `/mrc status` | Changes MRC event status. |
| `/mrc archive_completed` | Archives completed/cancelled MRC events. |
| `/mrc repair_events` | Recreates missing Discord Scheduled Events for MRC. |
| `/mrc delete` | Deletes an MRC event. |

### Scrims

| Command | What It Does |
| --- | --- |
| `/scrims create` | Creates a scrim event against a plain-text opponent. |
| `/scrims view` | Shows scrim events with pagination. |
| `/scrims upcoming` | Shows upcoming scrim events. |
| `/scrims status` | Changes scrim event status. |
| `/scrims archive_completed` | Archives completed/cancelled scrims. |
| `/scrims repair_events` | Recreates missing Discord Scheduled Events for scrims. |
| `/scrims delete` | Deletes a scrim event. |

### Tournaments

| Command | What It Does |
| --- | --- |
| `/tournaments create` | Creates a tournament event. |
| `/tournaments view` | Shows tournament events with pagination. |
| `/tournaments upcoming` | Shows upcoming tournament events. |
| `/tournaments status` | Changes tournament event status. |
| `/tournaments archive_completed` | Archives completed/cancelled tournaments. |
| `/tournaments repair_events` | Recreates missing Discord Scheduled Events for tournaments. |
| `/tournaments delete` | Deletes a tournament event. |

### Ignite

| Command | What It Does |
| --- | --- |
| `/ignite check_now` | Manually checks the configured Liquipedia page for new Ignite results. |

## Who Can Use Admin Commands?

Users can manage setup and event-management commands if they have any of:

- Administrator
- Manage Server
- Manage Events
- Any Manager Role configured in `/setup`

Schedule viewing commands are available to regular users:

- `/mrc view`
- `/mrc upcoming`
- `/scrims view`
- `/scrims upcoming`
- `/tournaments view`
- `/tournaments upcoming`
- `/upcoming`
- `/health`

## Per-Server Settings

Each Discord server has its own:

- MRC events
- Scrims
- Tournaments
- Manager roles
- Reminder roles
- Reminder channel
- Reminder lead time
- MRC event channel
- Scrim event channel
- Tournament event channel
- Default timezone
- Ignite channel
- Ignite source URL
- Ignite tracked team
- Ignite posted-result history

Changing setup in one server does not affect another server.

## Troubleshooting

### Slash Commands Do Not Show Up

- Restart the bot.
- Press `Ctrl+R` in Discord.
- Check the console for `Synced X command(s)`.
- Set `GUILD_ID` in `.env` while testing.
- Make sure the bot was invited with the `applications.commands` scope.

### Bot Cannot Create Scheduled Events

- Give the bot Manage Events or Create Events permission.
- Make sure the bot can view the channel where you are running commands.
- Make sure the bot's role is high enough in the server role list.

### Reminders Do Not Ping

Check `/setup`:

- Reminder Channel is set or the bot can post in the command channel.
- Reminder Roles are checked.
- Reminder Lead Time is set.
- The event is not Completed or Cancelled.

### Ignite Does Not Post

Check `/setup` and `/health`:

- Ignite Results Channel is set.
- Ignite auto-posting is enabled.
- Liquipedia source URL is correct.
- Tracked Team is blank or matches the team name you expect.

### MRC Session Times Out

The interactive `/mrc session` waits for typed messages for a limited time. If it times out, run the command again and continue entering the schedule.

## Project Files

```text
ScrimBot/
|-- main.py
|-- cogs/
|   |-- config.py
|   |-- events.py
|   |-- health.py
|   |-- ignite.py
|   |-- mrc.py
|   |-- scrim.py
|   |-- tournaments.py
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

`bot_data.db` is created automatically when the bot runs. Back it up if your schedule data matters.

## Run Tests

```bash
python -m unittest discover -s tests
```
