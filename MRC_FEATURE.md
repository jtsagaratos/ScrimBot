# MRC Schedule Management Feature

This document explains the MRC (tournament/competition) schedule management feature of ScrimBot.

## Overview

The MRC feature allows team managers to easily import, manage, and track tournament match schedules. All scheduled matches are automatically synced with Discord's native Scheduled Events feature.

## Database

The MRC system uses SQLite to store match data locally. The database file is `bot_data.db` and is created automatically on first run.

### MRC Matches Table Schema

```sql
mrc_matches (
    id INTEGER PRIMARY KEY,               -- Unique match identifier
    guild_id INTEGER NOT NULL,            -- Discord server ID
    datetime TEXT NOT NULL,               -- ISO format datetime
    round_group TEXT NOT NULL,            -- e.g., "Rounds 1-3"
    bracket TEXT NOT NULL,                -- "Upper" or "Lower"
    opponent TEXT,                        -- Optional opponent name
    discord_event_id TEXT,                -- Discord scheduled event ID
    created_at TEXT NOT NULL,             -- Creation timestamp
    updated_at TEXT NOT NULL              -- Last update timestamp
)
```

## Commands

### `/mrc import`
**Bulk import matches from multiline text**

- Accepts a block of text with multiple match entries
- Each line should follow the format: `Month Day Time(AM/PM) Rounds X-X Bracket`
- Automatically creates Discord Scheduled Events for each match
- Returns import statistics

**Example Input:**
```
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Upper
April 25 7:00 PM Rounds 1-3 Lower
April 26 2:00 PM Rounds 4-6 Upper
```

**Response:**
```
✅ **MRC Schedule Import Results**
Successfully imported: **4** matches
```

---

### `/mrc add`
**Add a single match with explicit parameters**

Parameters:
- `datetime_str` - Date and time (e.g., "April 25 1:00 PM")
- `rounds` - Round group (e.g., "Rounds 1-3")
- `bracket` - Bracket type: "Upper" or "Lower"

**Example:**
```
/mrc add datetime_str:"April 25 1:00 PM" rounds:"Rounds 1-3" bracket:"Upper"
```

---

### `/mrc session`
**Start an interactive session to add matches one-by-one**

- Bot enters interactive mode in your current channel
- Type each match line one at a time (same format as /mrc import)
- Type `done` to finish the session
- Type `cancel` to abort without saving
- Each successfully added match gets a ✅ reaction
- Timeout after 5 minutes of inactivity

**Example Flow:**
```
User: /mrc session
Bot: "🎮 **MRC Session started**... Enter matches one per message..."
User: "April 25 1:00 PM Rounds 1-3 Upper"
Bot: ✅
User: "April 25 4:00 PM Rounds 1-3 Upper"
Bot: ✅
User: "done"
Bot: "✅ **Session ended** - Successfully imported: **2** matches"
```

---

### `/mrc view`
**View all scheduled matches**

- Displays all matches for the server in chronological order
- Shows match ID, date, time, round group, and bracket
- Limited to 20 matches per message (shows count of remaining)
- Formatted as an embedded message for easy reading

**Sample Output:**
```
📅 MRC Schedule
Total matches: 4

[ID: 1] April 25
⏰ 1:00 PM
📍 Rounds 1-3
🏆 Upper

[ID: 2] April 25
⏰ 4:00 PM
📍 Rounds 1-3
🏆 Upper
```

---

### `/mrc edit`
**Edit an existing match**

Parameters:
- `match_id` (required) - ID of the match to edit
- `datetime_str` (optional) - New date and time
- `rounds` (optional) - New round group
- `bracket` (optional) - New bracket

**Features:**
- Update only the fields you provide
- Updates both database and Discord Scheduled Event
- Match ID can be found using `/mrc view`

**Examples:**
```
/mrc edit match_id:1 datetime_str:"April 26 2:00 PM"
/mrc edit match_id:2 bracket:"Lower"
/mrc edit match_id:3 datetime_str:"April 25 2:00 PM" rounds:"Rounds 4-6"
```

---

### `/mrc delete`
**Remove a match from the schedule**

Parameters:
- `match_id` - ID of the match to delete

**Features:**
- Removes from database
- Deletes corresponding Discord Scheduled Event
- Cannot be undone

**Example:**
```
/mrc delete match_id:1
```

---

## Date/Time Parsing

The system supports flexible datetime parsing for the `/mrc import` and `/mrc session` commands.

### Supported Formats

#### Standard Format (Recommended)
```
April 25 1:00 PM Rounds 1-3 Upper
April 25 1:00 PM Rounds 1-3 Lower
```

#### Month Variations
- Full month name: `April`, `January`, `December`
- Abbreviations also work in manual input

#### Time Format
- 12-hour format with AM/PM required
- Hours can be 1-12, minutes are 00-59
- Examples: `1:00 PM`, `2:30 AM`, `12:00 PM`

#### Round Format
- Flexible spacing: `Rounds 1-3`, `Rounds 1 - 3`
- Can use singular: `Round 1-3` (converted to `Rounds 1-3`)

#### Bracket Detection
- Case-insensitive: `upper`, `UPPER`, `Upper` all work
- Must be explicitly specified
- Only two options: `Upper` or `Lower`

---

## Discord Integration

### Scheduled Events

Each MRC match creates a Discord Scheduled Event with:

**Event Name:** `MRC S7 - Rounds X (Upper/Lower)` or `MRC S7 - Rounds X (Lower)`

**Description:** `"Vengeful MRC Match"`

**Location:** `"Online"`

**Privacy:** Guild-only (only visible to server members)

**Entity Type:** External (matches won't appear in voice channels)

### Permissions Required

The bot needs the following permissions to manage events:

- `MANAGE_EVENTS` - Create, edit, and delete scheduled events
- `SEND_MESSAGES` - Send confirmation messages
- `READ_MESSAGE_HISTORY` - For session mode message reading
- `READ_MESSAGES/VIEW_CHANNELS` - Basic channel access

Ensure your bot role is high enough in the server hierarchy to create events.

---

## Error Handling

### Common Errors

**"Bot does not have permission to create scheduled events"**
- Solution: Assign `MANAGE_EVENTS` permission to the bot role
- The bot's role should be positioned high in the role hierarchy

**"Team role not found"** (from `/scrim` command)
- Solution: Create a role for the team in your server
- The role name must contain or match the team name

**"Could not parse line"**
- Solution: Check the datetime format
- Use format: `Month Day Time(AM/PM) Rounds X-X Upper/Lower`
- Example: `April 25 1:00 PM Rounds 1-3 Upper`

**"Match with ID X not found"**
- Solution: Use `/mrc view` to see current match IDs
- Double-check the Match ID is correct

---

## Best Practices

### Bulk Import Tips
1. Prepare your schedule in a consistent format before importing
2. Copy/paste the entire schedule into the command
3. Check the report for any failed entries
4. Use `/mrc view` to verify matches were created correctly

### Session Mode Tips
1. Use when adding just a few matches
2. Careful with formatting - check each line before submitting
3. Type `cancel` if you make a mistake and want to restart

### Editing Tips
1. Always use `/mrc view` first to get current match IDs
2. Edit only the fields that need changing
3. Verify the Discord event updated by checking server calendar

### General Best Practices
1. **Always use `/mrc view` first** to see current state
2. **Back up your schedule** by exporting periodically (future feature)
3. **Test with one match** before bulk importing
4. **Verify Discord permissions** are set correctly before importing
5. **Set clear match formats** within your organization for consistency

---

## Limitations & Known Issues

- **Timezone:** Currently hardcoded to assume US Eastern Time for parsing. Timezone abbreviations in text are parsed but year defaults to 2026. Specify full year if needed in future versions.
- **20 match limit on view:** `/mrc view` displays max 20 matches per embedding to avoid message length limits
- **Reminder feature:** Currently placeholder - full implementation coming soon for 30-minute pre-match notifications
- **Year parsing:** Default year is 2026; specify full date if scheduling events in other years

---

## Future Enhancements

Planned features for future updates:

- [ ] Automatic @everyone reminders 30 minutes before matches
- [ ] Schedule export/backup functionality
- [ ] Team-specific schedule views
- [ ] Recurring match scheduling
- [ ] Result tracking integration
- [ ] Schedule statistics and analytics
- [ ] Multi-timezone support
- [ ] Custom Discord event templates

---

## Examples

### Example 1: Bulk Import Tournament Schedule

```
/mrc import
Schedule:
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Upper
April 25 7:00 PM Rounds 1-3 Lower
April 26 1:00 PM Rounds 4-6 Upper
April 26 4:00 PM Rounds 4-6 Lower
April 27 1:00 PM Rounds 7-9 Upper
```

**Result:** 6 matches imported, 6 Discord events created automatically

---

### Example 2: Add Single Match

```
/mrc add datetime_str:"April 25 1:00 PM" rounds:"Rounds 1-3" bracket:"Upper"
```

**Result:** Single match added with matching Discord event

---

### Example 3: Interactive Session

```
/mrc session
[Bot enters session mode in current channel]
User: April 25 1:00 PM Rounds 1-3 Upper
Bot: ✅
User: April 25 4:00 PM Rounds 1-3 Upper  
Bot: ✅
User: done
Bot: ✅ Session ended - Successfully imported: 2 matches
```

---

### Example 4: Edit Match Time

```
/mrc edit match_id:1 datetime_str:"April 26 2:00 PM"
```

**Result:** Match 1 rescheduled, Discord event updated automatically

---

### Example 5: View Schedule

```
/mrc view
```

**Result:** Displays all 6 matches in chronological order with full details

---

## Support & Troubleshooting

For issues with:

- **Datetime parsing:** Check the format exactly matches examples
- **Discord events:** Verify bot has `MANAGE_EVENTS` permission
- **Database:** Try deleting `bot_data.db` and restarting (will lose history)
- **Commands not appearing:** Restart the bot and wait 1-2 minutes for sync

---

## File Structure

```
cogs/
├── scrim.py          # Scrim command (existing)
└── mrc.py            # MRC commands (new)

models/
└── database.py       # Database management (new)

bot_data.db          # SQLite database (created at runtime)
```
