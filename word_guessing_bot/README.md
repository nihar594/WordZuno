# Word Zuno — Telegram Word Guessing Bot (`@WordZunoBot`)

Wordle-style bot for Telegram: 4/5/6/7-letter modes, 30 guesses, group multiplayer, leaderboards
(global / chat / today / week / month / year / all-time / by length), daily challenge, stats, admin tools.

Stack: Python 3.12+, python-telegram-bot 22, SQLite (aiosqlite), Docker, long polling.

## 1. Get the bot token
1. Open [@BotFather](https://t.me/BotFather) → `/newbot` → name `Word Zuno` → username `WordZunoBot`.
2. Copy the token it gives you (looks like `123456:ABC...`). **Never share it or commit it.**
3. Optional in BotFather: `/setuserpic` (upload your `logo.png`), `/setdescription`, `/setabouttext`,
   `/setjoingroups` = Enabled, `/setprivacy` = **Disable** (so the bot can read guesses in groups;
   alternatively make the bot a group admin).

## 2. Install & run locally
```bash
cd word_guessing_bot
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # then edit .env
python main.py
```
In `.env` set at least `BOT_TOKEN` and `ADMIN_IDS` (send `/id` to the bot to learn your numeric ID).
Also set `UPDATES_URL`, `DISCUSSION_URL`, `DONATE_URL` to your own channel / group / donation links
(they default to the bot's own link so every button works out of the box).

## 3. Add your images
Put `assets/banner.png` (welcome banner) in place — the bot picks it up automatically on `/start`
(without it, the welcome is sent as text). Upload `logo.png` as the bot photo through BotFather (`/setuserpic`).

## 4. Docker
```bash
cp .env.example .env && nano .env
docker compose up -d --build        # runs with a persistent ./storage volume
docker compose logs -f              # live logs
docker compose restart              # restart
```
Without compose:
```bash
docker build -t wordzuno .
docker run -d --name wordzuno --restart unless-stopped --env-file .env -v $(pwd)/storage:/app/storage wordzuno
```

## 5. Free hosting — be realistic
The bot uses **long polling**, so it must be *running* to answer. No free host guarantees 24/7 uptime.

| Option | Notes |
|---|---|
| **Oracle Cloud "Always Free" VM / Google Cloud e2-micro free tier** | Best fit: a real VM with a real disk, runs 24/7 with `docker compose`. Needs a card for sign-up; check current free-tier terms and regions. |
| Home PC / Raspberry Pi / old phone (Termux) | Free, works fine, only runs while powered on and online. |
| Render / Koyeb / Railway / Fly.io style platforms | Free plans change often. Free web services usually **sleep after inactivity** (a sleeping polling bot is offline) and many free plans have **no persistent disk** — your SQLite file would be wiped on redeploy. If you use one: attach a persistent volume (usually paid), set `PORT` so the built-in health endpoint answers pings, and use `/backup` regularly. |

Always keep `DB_PATH` on persistent storage (volume/disk). If the disk is ephemeral, all points/stats are lost on restart.
`PORT=8080` starts a tiny `OK` HTTP endpoint for hosts that require an open port or an uptime pinger.

## 6. Operations
* **Restart recovery:** active games, guesses, maintenance mode and bans are stored in SQLite and resume after a restart.
  Games idle for `GAME_TIMEOUT_HOURS` (24h) are expired automatically.
* **Graceful shutdown:** `Ctrl+C` / `SIGTERM` stops polling and closes the database cleanly.
* **Logs:** JSON lines on stdout and in `logs/bot.log` (rotating, 5 × 2 MB). Set `LOG_LEVEL=DEBUG` for more.
* **Backups:** the admin command `/backup` sends you a consistent copy of the database. Manually:
  `sqlite3 storage/wordzuno.db ".backup 'backup.db'"` or copy the file while the bot is stopped.
  Restore by putting the file back at `DB_PATH` and starting the bot.
* **Update words:** edit `data/words.txt` (valid guesses) / `data/answers.txt` (secret words, common words only),
  then send `/reloadwords` — no restart needed.

## 7. Commands
Players: `/start /help /rules /new /new4 /new5 /new6 /new7 /hint /skip /cancel /daily /leaderboard /stats /profile /history /rank /id`
Admins (IDs from `ADMIN_IDS` only): `/richtest /emojipack /emojiset /emojitest /emojireset /admin /broadcast /ban /unban /userinfo /botstats /maintenance on|off /reloadwords /backup`

* `/new` starts a `DEFAULT_LENGTH` (5) game. Any member can start a group game; `/cancel` & `/skip` are for the starter or group admins.
* Every message that is a single 4–7 letter word is treated as a guess while a game of that length is running; all other chat is ignored.
* Invalid and repeated words never use an attempt. Duplicate letters follow real Wordle rules.
* Only one game per chat at a time; each chat is independent and guarded by locks + DB transactions.
* Scoring (`.env`): `POINTS_WIN=15`, `DAILY_BONUS`, `DAILY_STREAK_BONUS`, `STREAK_BONUS`, `MULTIPLAYER_BONUS`.
  A win is rewarded exactly once (status-guarded update + unique transaction index).
* Daily challenge: `/daily` in private chat, one shared word per UTC day, one attempt per player, daily ranking button.

### Extras taken from the original WordSeek (MIT)
* **Word meanings:** after a win / loss / `/skip` the bot shows pronunciation, meaning and example (`data/meanings.json`,
  2,300+ five-letter words from the original project, MIT license © Binamra Lamsal). Words without data show nothing extra.
* `/score [@user|id] [group|global] [today|week|month|year|all] [4-7]` and `/myscore` — score, rank, wins, streaks.
* `/end` (same as `/cancel`), `/allowonlylen 5 4` (group admins: limit word lengths per chat; `/allowonlylen all` resets).
* `/transfer <from> <to>` (admin) — move all points/games/stats from one user to another (ID or @username).
* `/ban` `/unban` `/userinfo` also accept `@username`.
* Random reaction (🎉🏆💯…) on the winning guess (`REACTIONS=off` to disable).
* `SCORING_MODE=remaining` → points = guesses left (`30 − guesses used`, like the original); default `fixed` = `POINTS_WIN`.
Not ported: forum-topic mode, captcha, message tracking, daily-word image.

### /help (WordSeek style)
`/help` is a rich message like the reference: headings, numbered list, colored example letters, command table, collapsible
"Daily Mode" block and navigation buttons (How to Play · Leaderboard & Scores · Group Settings · Other Commands · Updates ·
Donate · Discussion; owners also get 👑 Admin Commands in private chat). Set `GITHUB_URL` to show a "GitHub Repo" button.
If Telegram refuses rich messages the bot sends the older plain-text help instead.
`/leaderboard [group|global] [today|week|month|year|all] [4-7]` and `/score ...` use the same defaults as the reference
(this chat, today, 5-letter).

## 8. Tests
```bash
pip install pytest
python -m pytest tests -q
```
69 tests: evaluation/duplicate letters, validation, all lengths, 30-guess loss, rewards (no double award), leaderboard
filters & pagination, multiplayer & simultaneous guesses, daily + streaks, persistence/restart, SQL-injection safety,
rate limiting, admin permissions/ban/maintenance/broadcast/backup, and end-to-end handler flows against a fake Telegram API.

## 9. Pill letters (rich message, default)
`BOARD_STYLE=rich` (default) sends the board as a Telegram **rich message**: every letter is a colored pill button —
green = correct, red = absent, default = wrong spot — exactly the technique used by the original WordSeek source.
Tapping a pill explains its color. As admin send `/richtest` once to confirm Telegram accepts rich messages for your bot;
if Telegram refuses (older Bot API access), the bot automatically falls back to the emoji text board.
Set `BOARD_STYLE=text` to force the emoji board.

### Optional: pill letters via custom emoji (only used in `text` board mode)
WordSeek's pill letters are Telegram *custom emoji*. Setup (admin only, in the bot's DM):
1. Find a custom-emoji pack with A–Z letters in green / yellow / grey-or-red. Link `t.me/addemoji/NAME` → pack name is `NAME`.
2. `/emojipack NAME GYB` → maps the pack in blocks of 26 (A–Z): 1st block green, 2nd yellow, 3rd grey. Use another order
   (e.g. `BGY`) if your pack's color order differs. Single color from a message: `/emojiset G` + 26 custom emojis (A→Z).
3. `/emojitest` → you should see A–Z pills. `/emojireset` → back to 🟩🟨⬛.
The mapping is saved in `emoji.json` next to the database (so keep the volume), and works after restart.
**Important:** Telegram only lets some bots send custom emoji (historically bots whose username was bought on Fragment).
If `/emojitest` shows plain squares, Telegram is not allowing it for your bot — run `/emojireset`.
Each message can hold ~100 entities, so the newest guesses use pills and very old rows fall back to plain tiles.

## 10. Notes on the WordSeek look
* Layouts, texts, buttons and leaderboard follow your screenshots. Letter tiles are 🟩🟨⬛ emoji with full-width letters
  underneath, because the pink "pill" letters in the reference are Telegram *custom emojis*, which normal bots can't send.
* Button colors (blue selected / green Donate) use Telegram's new button `style`; very old Telegram apps show them uncolored.
* The leaderboard has a 4-button length row (4/5/6/7) so 7-letter mode is also filterable. Tap the active length again to clear it.
* `BOARD_MODE=resend` (default) posts a fresh board after each guess like WordSeek (old board is deleted);
  `BOARD_MODE=edit` edits one board message instead.

## Project layout
```
main.py  config.py  requirements.txt  .env.example  Dockerfile  docker-compose.yml
handlers/   start game leaderboard profile help daily admin common
services/   word_service game_service scoring leaderboard_service context
database/   db models migrations
keyboards/  main_menu leaderboard help_menu
utils/      formatting validators logger ratelimit
assets/     banner.png (yours) · data/ words.txt answers.txt · tests/
```
