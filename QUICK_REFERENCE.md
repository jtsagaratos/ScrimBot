# ScrimBot Quick Reference

## Scrim Commands

### `/scrim <team_name> <datetime>`
Create a quick scrim event against a team.

**Examples:**
- `/scrim Team1 4/22/26 4pm EST`
- `/scrim Valorant 4/22 3pm`

---

## MRC Tournament Commands

### `/mrc import`
Bulk import tournament schedule from multiline text.

**Format:** Each line = `Month Day Time(AM/PM) Rounds X-X Upper/Lower`

**Example Input:**
```
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Upper
April 25 7:00 PM Rounds 1-3 Lower
```

---

### `/mrc add` `datetime_str` `rounds` `bracket`
Add a single match.

**Example:**
```
/mrc add datetime_str:"April 25 1:00 PM" rounds:"Rounds 1-3" bracket:"Upper"
```

---

### `/mrc session`
Start interactive mode to add matches one-by-one.
- Type each match line
- Type `done` to finish
- Type `cancel` to abort
- ✅ = successful add

---

### `/mrc view`
Display all scheduled matches.
- Shows ID, date, time, round, bracket
- Max 20 per message

---

### `/mrc edit` `match_id` [datetime_str] [rounds] [bracket]
Edit an existing match.

**Examples:**
```
/mrc edit match_id:1 datetime_str:"April 26 2:00 PM"
/mrc edit match_id:2 bracket:"Lower"
/mrc edit match_id:3 rounds:"Rounds 4-6"
```

---

### `/mrc delete` `match_id`
Delete a match and its Discord event.

**Example:**
```
/mrc delete match_id:1
```

---

## DateTime Format Reference

### Supported Formats
- `4/22/26 4pm EST` ✅
- `April 22 4:00 PM EST` ✅
- `2026-04-22 16:00 EST` ✅

### Required Elements
- Month (full name or abbreviation)
- Day (1-31)
- Time (12-hour format WITH AM/PM)
- Timezone (EST, PST, UTC, etc.)

### Timezone Abbreviations
| Timezone | Abbreviation |
|----------|------------|
| Eastern  | EST, EDT, ET |
| Central  | CST, CDT, CT |
| Mountain | MST, MDT, MT |
| Pacific  | PST, PDT, PT |
| Universal | UTC, GMT |

---

## MRC Match Format Reference

### Line Format
`Month Day Time Rounds X-X Bracket`

### Examples
- `April 25 1:00 PM Rounds 1-3 Upper` ✅
- `April 25 4:00 PM Rounds 4-6 Lower` ✅
- `April 26 2:30 PM Rounds 7-9 Upper` ✅

### Required Elements
- Month (full name, case-insensitive)
- Day (1-31)
- Time (12-hour format with AM/PM)
- Rounds (e.g., "Rounds 1-3", "Rounds 4-6")
- Bracket ("Upper" or "Lower", case-insensitive)

---

## Common Workflows

### Scenario 1: Import Full Tournament
```
/mrc import
[Paste 10+ matches in bulk]
→ Bot creates all matches + Discord events
```

### Scenario 2: Add Matches One-by-One
```
/mrc session
April 25 1:00 PM Rounds 1-3 Upper
April 25 4:00 PM Rounds 1-3 Upper
done
```

### Scenario 3: Check Schedule
```
/mrc view
[See all matches with IDs]
```

### Scenario 4: Fix Time Error
```
/mrc edit match_id:1 datetime_str:"April 26 2:00 PM"
[Match 1 updated + Discord event synced]
```

### Scenario 5: Remove Match
```
/mrc delete match_id:1
[Match removed from DB + Discord event deleted]
```

---

## Troubleshooting Quick Fixes

| Problem | Solution |
|---------|----------|
| Commands not showing | Restart bot, wait 2 min |
| Parse error | Check format: `Month Day Time(AM/PM) Rounds X-X Bracket` |
| Permission denied | Add `MANAGE_EVENTS` permission to bot |
| Match ID not found | Use `/mrc view` to see current IDs |
| Team role not found | Ensure role exists in server |

---

## Permissions Needed

Bot role must have:
- ✅ `MANAGE_EVENTS`
- ✅ `SEND_MESSAGES`
- ✅ `READ_MESSAGES`
- ✅ Role positioned high in hierarchy

---

## Database

- **Location:** `bot_data.db` (auto-created)
- **Reset:** Delete file and restart bot
- **Backup:** Copy `bot_data.db` to save

---

## Documentation Links

- **Full Guide:** `README.md`
- **MRC Details:** `MRC_FEATURE.md`
- **Implementation:** `IMPLEMENTATION_SUMMARY.md`
- **This Sheet:** `QUICK_REFERENCE.md`

---

## Setup Reminder

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Setup .env
copy .env.example .env
# Edit and add DISCORD_TOKEN

# 3. Run bot
python main.py
```

---

**Last Updated:** April 21, 2026  
**Status:** ✅ Ready to Use
