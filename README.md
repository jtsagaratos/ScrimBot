# ScrimBot User Guide

ScrimBot is a Discord bot for scrims, MRC event scheduling, Ignite result tracking, reminders, and upcoming schedule views. It creates Discord Scheduled Events, stores data per server, and shows Discord-native timestamps so every player sees local times in their own timezone.

## What The Bot Does

- Create scrim events against plain-text opponent names.
- Add, import, edit, view, archive, and delete MRC events.
- Send 30-minute MRC and scrim reminders to configured channels.
- Ping configured reminder roles.
- Show upcoming MRC events and scrims.
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

For fastest command updates while testing, set `GUILD_ID` to your Discord server ID. With `GUILD_ID=0`, the bot syncs slash commands globally, which can take longer to appear in Discord.

Use `/setup` to open the interactive setup panel for channels, roles, timezone, and Ignite settings.

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

Run `/setup` in the Discord server where you want to use the bot. It opens an interactive setup panel with buttons, role menus, channel menus, and text prompts.

Open setup:

```text
/setup
```

From there you can configure:

- Default timezone
- Manager roles
- Shared reminder channel for MRC and scrims
- MRC event posting channel
- MRC reminder ping roles
- Scrim/tournament event posting channel
- Scrim ping roles
- Ignite result channel
- Ignite source URL
- Ignite tracked team
- Ignite auto-posting

### 1. Set Manager Roles

This lets staff manage the bot without needing full Discord admin permissions.

Use `/setup`, choose **Roles**, then use the **Check manager roles** menu. Checked roles are managers; unchecked roles are removed from the manager list.

### 2. Set The Default Timezone

Use your main tournament timezone.

Use `/setup`, choose **Timezone**, then enter a timezone.

You can also use abbreviations like `EST`, `PST`, `UTC`, `MT`, or full IANA names like `Europe/London`.

### 3. Set The Shared Reminder Channel

Use `/setup`, choose **Channels**, then choose the reminder channel. Both MRC and scrim 30-minute reminders use this channel.

### 4. Set Event Posting Channels

Use `/setup`, choose **Channels**, then choose the MRC event channel, scrim event channel, and tournament event channel. New events are posted in their respective channels when staff create them.

### 5. Add Reminder Ping Roles

Use `/setup`, choose **Roles**, then use the **Check MRC reminder ping roles** menu. Checked roles receive reminders; unchecked roles are removed.

Scrim pings are configured separately:

Use `/setup`, choose **Roles**, then use the **Check scrim ping roles** menu. Checked roles receive scrim pings/reminders; unchecked roles are removed.

The scrim ping roles are also used for 30-minute scrim reminders.

### 6. Set Up Ignite Results

Use `/setup`, choose **Channels** for the result channel, then choose **Ignite** for source/team/auto-posting.

Optional: only post results for one team.

Use `/setup`, choose **Ignite**, then choose **Source / Team**.

Enable auto-posting:

Use `/setup`, choose **Ignite**, then choose **Toggle Auto**.

Check Ignite setup:

Use `/setup` again to review the current setup summary.

### 7. Check Bot Health

```text
/health
```

This checks the database, background tasks, Ignite source reachability, and Discord latency.

## Common Workflows

### Schedule One Scrim

The team name is plain text. The opponent does not need a Discord role.

```text
/scrim create team:"Team1" date_time:"4/22/26 4pm EST" duration_hrs:2
```

With a timezone override:

```text
/scrim create team:"Team1" date_time:"April 22 4:00 PM" duration_hrs:2 timezone:"America/Denver"
```

The bot creates a Discord Scheduled Event with the required duration and stores the scrim for `/upcoming`.
The Discord event description includes the bot's prefixed `Event ID`. Scrim IDs start with `S`, like `S1`.

Edit a scrim later:

```text
/edit event_id:S1
```

Manage scrims like MRC events:

```text
/scrim view
/scrim upcoming days:14
/scrim status event_id:S1 status:"Completed"
/scrim delete event_id:S1
```

Set roles to ping for scrim reminders:

```text
/setup
```

Choose **Roles**, then check the scrim ping roles.

### Schedule One Tournament

Tournament names are plain text and use `T` event IDs.

```text
/tournament create name:"Ignite Qualifier" date_time:"4/24/26 6pm EST" duration_hrs:3
```

Edit a tournament later:

```text
/edit event_id:T1
```

Manage tournaments:

```text
/tournament view
/tournament upcoming days:14
/tournament status event_id:T1 status:"Completed"
/tournament delete event_id:T1
```

### Add One MRC Event

```text
/mrc add season:7 duration_hrs:2 date_time:"April 25 1:00 PM" name:"Rounds 1-3"
```

Put the timezone in the date/time when needed:

```text
/mrc add season:7 duration_hrs:2 date_time:"4/20/26 3PM EST" name:"Rounds 7-9"
```

The name can be any title:

```text
/mrc add season:7 duration_hrs:2 date_time:"April 25 7:00 PM America/Denver" name:"Grand Finals"
```

### Bulk Import MRC Events

Use `/mrc import` with a required duration, then paste lines in this format:

```text
/mrc import schedule:"April 25 1:00 PM Rounds 1-3 Upper" duration_hrs:2
```

```text
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Upper
April 25 7:00 PM Rounds 1-3 Lower
April 25 9:00 PM Rounds 7-9
```

Lines can include a timezone before or after the title:

```text
April 25 1:00 PM America/Denver Rounds 1-3 Upper
April 25 1:00 PM Rounds 1-3 Upper America/Denver
April 25 4:00 PM Rounds 1-3 Lower PST
```

### Add MRC Events Interactively

```text
/mrc session season:7 duration_hrs:2
```

Then send one line at a time:

```text
April 25 1:00 PM Rounds 1-3
4/20/26 3PM EST Rounds 7-9
April 25 4:00 PM Rounds 1-3 Upper
done
```

The text after the date/time becomes the event title. A final `Upper` or `Lower` is optional. Use `cancel` to stop.

### View The Schedule

```text
/mrc view
```

By default this hides completed, cancelled, and archived events.

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

MRC events only:

```text
/mrc upcoming days:14
```

MRC events and scrims together:

```text
/upcoming days:14
```

### Edit An Event

```text
/edit event_id:M1
```

Discord opens a prefilled form with:

- Date/Time
- Timezone
- Duration Hours
- Rounds
- Bracket

Submit the form to update the database and the linked Discord Scheduled Event.
Use `/mrc status` to change event status.
The linked Discord Scheduled Event description includes the bot's prefixed `Event ID`. MRC IDs start with `M`, like `M1`.

### Change Event Status

```text
/mrc status event_id:M1 status:"In Progress"
/mrc status event_id:M1 status:"Completed"
```

Supported statuses:

- `Scheduled`
- `Checked In`
- `In Progress`
- `Completed`
- `Cancelled`

### Archive Completed Events

```text
/mrc archive_completed
```

This archives completed and cancelled events so normal schedule views stay clean.

### Repair Missing Discord Events

If Discord Scheduled Events were deleted manually, recreate them:

```text
/mrc repair_events
```

Include completed/cancelled events:

```text
/mrc repair_events include_completed:true
```

### Delete An MRC Event

```text
/mrc delete event_id:M1
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

### Setup

Use `/setup` first. It opens an interactive setup panel for timezone, manager roles, the shared reminder channel, MRC event channel, scrim event channel, tournament event channel, MRC reminder roles, scrim ping roles, and Ignite posting settings.

| Command | What It Does |
| --- | --- |
| `/setup` | Opens the interactive setup panel. |

### Bot Health

| Command | What It Does |
| --- | --- |
| `/health` | Checks database, task, Ignite, and latency health. |

### Scrims

| Command | What It Does |
| --- | --- |
| `/scrim create team date_time duration_hrs` | Creates a scrim Scheduled Event against a plain-text opponent. |
| `/scrim view` | Shows active scrim events with pagination. |
| `/scrim upcoming` | Shows upcoming scrim events. |
| `/scrim status event_id status` | Sets scrim event status. |
| `/scrim archive_completed` | Archives completed/cancelled scrim events. |
| `/scrim repair_events` | Recreates missing Discord Scheduled Events for scrims. |
| `/scrim delete event_id` | Deletes a scrim and its linked event. |
| `/upcoming days:14` | Shows upcoming MRC events, scrims, and tournaments together. |

### Tournaments

| Command | What It Does |
| --- | --- |
| `/tournament create name date_time duration_hrs` | Creates a tournament Scheduled Event. |
| `/tournament view` | Shows active tournament events with pagination. |
| `/tournament upcoming` | Shows upcoming tournament events. |
| `/tournament status event_id status` | Sets tournament event status. |
| `/tournament archive_completed` | Archives completed/cancelled tournament events. |
| `/tournament repair_events` | Recreates missing Discord Scheduled Events for tournaments. |
| `/tournament delete event_id` | Deletes a tournament and its linked event. |

### MRC Scheduling

| Command | What It Does |
| --- | --- |
| `/mrc add season duration_hrs date_time name` | Adds one MRC event. The name becomes the Scheduled Event title after `MRC S# -`. |
| `/mrc import` | Bulk imports many MRC events from pasted text with one required duration for all imported events. |
| `/mrc session season duration_hrs` | Adds events one by one in chat with one required season and duration for the session. |
| `/mrc view` | Shows active MRC events with pagination. |
| `/mrc upcoming` | Shows upcoming MRC events. |
| `/mrc status` | Sets event status. |
| `/mrc archive_completed` | Archives completed/cancelled events. |
| `/mrc repair_events` | Recreates missing Discord Scheduled Events. |
| `/mrc delete` | Deletes an event and its linked Discord Scheduled Event. |

### Shared Event Actions

| Command | What It Does |
| --- | --- |
| `/edit event_id` | Opens the correct edit form for `M#` MRC IDs, `S#` scrim IDs, or `T#` tournament IDs. |

### Ignite

| Command | What It Does |
| --- | --- |
| `/ignite check_now` | Checks Liquipedia immediately. |

## Permissions

Users can manage schedule/config commands if they have any of:

- Administrator
- Manage Server
- Manage Events
- any configured manager role from `/setup`

The bot itself needs:

- View Channels
- Send Messages
- Read Message History
- Manage Events / Create Events
- Use Application Commands

## Per-Server Behavior

All main data is separated by Discord server:

- MRC events
- scrims
- tournaments
- shared reminder channel
- MRC event posting channel
- scrim event posting channel
- tournament event posting channel
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
April 25 1:00 PM Rounds 1-3
4/20/26 3PM EST Rounds 7-9
```

Required:

- month name or numeric date
- day
- 12-hour time with AM/PM
- event title text after the date/time

Optional:

- timezone abbreviation or IANA timezone, such as `EST` or `America/Denver`
- a final `Upper` or `Lower` bracket label

### Scrim Pings Do Not Happen

Add at least one scrim ping role:

```text
/setup
```

Choose **Roles**, then check at least one scrim ping role.

### Ignite Does Not Post

Check:

```text
/setup
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
