"""Rich-message help pages (headings, lists, tables, collapsible blocks) — WordSeek style."""
from __future__ import annotations

from config import Settings
from utils.formatting import esc
from utils.rich import example_button as ex


def how_to_play(s: Settings) -> str:
    n, d = s.max_guesses, s.default_length
    return f"""<h3>How to Play {esc(s.bot_name)}</h3>
<blockquote>
<ol>
<li>Start a game using /new, /new4, /new5, /new6, or /new7</li>
<li>Guess the hidden word</li>
<li>After each guess, every letter becomes a colored button (see below)</li>
<li>First person to guess correctly wins!</li>
<li>Maximum {n} guesses per game</li>
</ol>
</blockquote>

<h4>Reading the colors</h4>
<p>{ex("correct", "S")} <b>Green</b>: right letter, right spot</p>
<p>{ex("present", "T")} <b>No color</b>: right letter, wrong spot</p>
<p>{ex("absent", "X")} <b>Red</b>: letter isn't in the word</p>
<p><i>Tap any letter button to see what it means. The no color button follows your Telegram theme.</i></p>

<p><b>Example guess:</b></p>
<p>{ex("correct", "S")}{ex("present", "T")}{ex("absent", "A")}{ex("absent", "R")}{ex("correct", "E")}</p>

<h4>Word Length Modes</h4>
<blockquote>
<ul>
<li>/new: start the default {d}-letter game</li>
<li>/new 4: start a specific length (4, 5, 6, or 7)</li>
<li>/new4: start a 4-letter game</li>
<li>/new5: start a 5-letter game</li>
<li>/new6: start a 6-letter game</li>
<li>/new7: start a 7-letter game</li>
</ul>
</blockquote>

<h4>Basic Commands</h4>
<table bordered compact>
<tr><th>Command</th><th>What it does</th></tr>
<tr><td>/new</td><td>Start a new game (default {d} letters)</td></tr>
<tr><td>/new4 /new5 /new6 /new7</td><td>Start a game with that length</td></tr>
<tr><td>/hint</td><td>Reveal one letter (max {s.hints_per_game} per game)</td></tr>
<tr><td>/end</td><td>End current game (starter or admin only)</td></tr>
<tr><td>/skip</td><td>Reveal the word and end the game</td></tr>
<tr><td>/help</td><td>Show this help menu</td></tr>
<tr><td>/daily</td><td>Play Daily {esc(s.bot_name)} (private chat only)</td></tr>
</table>

<details><summary>Daily Mode (Private Chat Only)</summary>
<blockquote>
<ul>
<li>Start a daily game using /daily command</li>
<li>Works like New York Times Wordle: one fixed word per day, the same for everyone</li>
<li>You get {s.daily_max_guesses} guesses per daily puzzle and one official attempt per day</li>
<li>A new puzzle unlocks every day at 00:00 <code>UTC</code></li>
<li>You earn bonus points and build a streak by solving the daily puzzle on consecutive days</li>
<li>You cannot play a normal game and Daily at the same time:
<ul>
<li>If a normal game is running, end it before using /daily</li>
<li>If Daily is active, /cancel forfeits today's attempt</li>
</ul>
</li>
</ul>
</blockquote>
</details>"""


def scores(s: Settings) -> str:
    return f"""<h3>Leaderboard &amp; Scores</h3>

<h4>Quick Examples</h4>
<blockquote>
<table bordered compact>
<tr><th>Command</th><th>What it shows</th></tr>
<tr><td><code>/leaderboard</code></td><td>Group, today ({s.default_length}-letter)</td></tr>
<tr><td><code>/leaderboard 4</code></td><td>4-letter, group, today</td></tr>
<tr><td><code>/leaderboard global week 6</code></td><td>Global, this week, 6-letter</td></tr>
<tr><td><code>/leaderboard month</code></td><td>This group's monthly board</td></tr>
<tr><td><code>/score</code></td><td>Your score (group, today, {s.default_length}-letter)</td></tr>
<tr><td><code>/score 6</code></td><td>Your 6-letter stats</td></tr>
<tr><td><code>/score @username global all 4</code></td><td>Full 4-letter global history for a user</td></tr>
<tr><td><code>/score 123456789 month</code></td><td>Monthly stats for a user ID</td></tr>
</table>
</blockquote>

<h4>Leaderboard Command</h4>
<blockquote>
<p><b>Syntax:</b> <code>/leaderboard [scope] [period] [length]</code></p>
<p>All parameters are optional and can be used in any order.</p>
<table bordered compact>
<tr><th>Parameter</th><th>Options</th></tr>
<tr><td>Scope</td><td><code>group</code> (default), <code>global</code></td></tr>
<tr><td>Period</td><td><code>today</code> (default), <code>week</code>, <code>month</code>, <code>year</code>, <code>all</code></td></tr>
<tr><td>Length</td><td><code>4</code>, <code>5</code> (default), <code>6</code>, <code>7</code></td></tr>
</table>
</blockquote>

<h4>Score Command</h4>
<blockquote>
<p><b>Syntax:</b> <code>/score [target] [scope] [period] [length]</code></p>
<p>All parameters are optional and can be used in any order.</p>
<p><b>Target (optional):</b></p>
<ul>
<li>Leave empty for your own score</li>
<li><code>@username</code>: look up by username</li>
<li><code>user_id</code>: look up by Telegram user ID</li>
</ul>
<p><b>Scope, period &amp; length:</b> same as <code>/leaderboard</code></p>
</blockquote>

<h4>Personal Stats</h4>
<blockquote>
<p><code>/stats</code>, <code>/profile</code>, <code>/history</code>, <code>/rank</code> and <code>/myscore</code> show your games, rank and streaks.</p>
</blockquote>"""


def group_settings(s: Settings) -> str:
    return """<h3>Group Settings (Admin Only)</h3>

<h4>Word Lengths</h4>
<details><summary><code>/allowonlylen</code>: restrict word lengths</summary>
<blockquote>
<ul>
<li><code>/allowonlylen 4</code></li>
<li><code>/allowonlylen 5 6</code></li>
<li><code>/allowonlylen all</code>: allow every length again</li>
</ul>
<p>You can allow one or more of: 4, 5, 6, 7. The first number you specify becomes the default length for <code>/new</code> in this chat.</p>
<p>If not configured, all lengths (4, 5, 6, 7) are allowed by default.</p>
</blockquote>
</details>

<h4>Ending Games</h4>
<details><summary><code>/end</code>, <code>/cancel</code> and <code>/skip</code></summary>
<blockquote>
<p>Only the player who started the game or a group admin can end it.</p>
<ul>
<li><code>/end</code> or <code>/cancel</code>: stop the game without a result</li>
<li><code>/skip</code>: reveal the word and end the game</li>
</ul>
</blockquote>
</details>

<h4>Tips</h4>
<blockquote>
<p>Make the bot a group admin so it can read every guess. Everyone plays the same word, and the first correct guess wins the points.</p>
</blockquote>"""


def other_commands(s: Settings) -> str:
    return """<h3>Other Commands</h3>

<blockquote>
<p><b><code>/id</code></b>: get your Telegram and chat IDs</p>
<p>Reply to a message to also see that user's ID.</p>
</blockquote>

<blockquote>
<p><b><code>/rules</code></b>: short game rules</p>
<p><b><code>/hint</code></b>: reveal one letter of the word</p>
<p><b><code>/daily</code></b>: today's shared word challenge</p>
</blockquote>"""


def admin_commands(s: Settings) -> str:
    return """<h3>Admin Commands (Bot Owner Only)</h3>

<blockquote>
<table bordered compact>
<tr><th>Command</th><th>What it does</th></tr>
<tr><td><code>/ban [user_id|@user]</code></td><td>Ban a user from using the bot globally</td></tr>
<tr><td><code>/unban [user_id|@user]</code></td><td>Unban a previously banned user</td></tr>
<tr><td><code>/transfer &lt;from_user&gt; &lt;to_user&gt;</code></td><td>Transfer scores between users</td></tr>
<tr><td><code>/broadcast</code></td><td>Broadcast to all users (reply to a message or add text)</td></tr>
<tr><td><code>/userinfo [user_id|@user]</code></td><td>Show a user's details</td></tr>
<tr><td><code>/maintenance on|off</code></td><td>Toggle maintenance mode</td></tr>
<tr><td><code>/reloadwords</code></td><td>Reload the word lists</td></tr>
<tr><td><code>/backup</code></td><td>Send a database backup</td></tr>
<tr><td><code>/richtest</code></td><td>Check that colored letter buttons work</td></tr>
</table>
</blockquote>

<details><summary><code>/botstats</code>: bot statistics</summary>
<blockquote>
<ul>
<li>Total users, groups, games and guesses</li>
<li>Active players today, database size and uptime</li>
</ul>
</blockquote>
</details>"""


PAGES = {"howto": how_to_play, "scores": scores, "group": group_settings, "other": other_commands,
         "admin": admin_commands}
