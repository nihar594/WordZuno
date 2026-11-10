"""Telegram "rich messages": every letter is a colored <tg-button> pill (same technique as WordSeek)."""
from __future__ import annotations

import json
import random
import warnings

from utils.formatting import esc

# do_api_request is the intended way to call Bot API methods PTB does not model yet (rich messages)
warnings.filterwarnings("ignore", message=".*do_api_request.*")

_ZERO_WIDTH = ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]
_STYLE = {"G": ' style="success"', "Y": "", "B": ' style="danger"'}  # green / default / red
_STATE = {"G": "correct", "Y": "present", "B": "absent"}


def _noise() -> str:
    # random invisible characters make the pills a little wider and varied, like the reference bot
    return "".join(random.choices(_ZERO_WIDTH, k=random.randint(1, 6)))


def rich_row(word: str, pattern: str) -> str:
    buttons = "".join(
        f'<tg-button type="callback_data"{_STYLE[c]} data="wh:{_STATE[c]}:{ch.upper()}">'
        f"{_noise()}{ch.upper()}{_noise()}</tg-button>"
        for ch, c in zip(word, pattern)
    )
    return f"<p>{buttons}</p>"


def rich_board_html(game, guesses) -> str:
    title = "Daily challenge" if game.game_mode == "daily" else f"{game.word_length}-letter mode"
    rows = "".join(rich_row(g.guessed_word, g.result) for g in guesses)
    return f"<h3>{esc(title)}</h3><p><i>{len(guesses)}/{game.max_guesses} guesses</i></p>{rows}"


def rich_params(html: str) -> str:
    return json.dumps({"html": html})


async def send_rich(bot, chat_id: int, html: str, reply_markup=None) -> int:
    kw = {"chat_id": chat_id, "rich_message": {"html": html}}
    if reply_markup is not None:
        kw["reply_markup"] = reply_markup
    res = await bot.do_api_request("sendRichMessage", api_kwargs=kw)
    return int(res["message_id"])


async def edit_rich(bot, chat_id: int, message_id: int, html: str, reply_markup=None) -> None:
    kw = {"chat_id": chat_id, "message_id": message_id, "rich_message": {"html": html}}
    if reply_markup is not None:
        kw["reply_markup"] = reply_markup
    await bot.do_api_request("editMessageText", api_kwargs=kw)


HINTS = {
    "correct": '🟩 "{l}" is in the word and in the right spot.',
    "present": '🟨 "{l}" is in the word, but in a different spot.',
    "absent": '🟥 "{l}" isn\'t in the word.',
}


def example_button(state: str, letter: str) -> str:
    """Same pill + callback as in a real game, so tapping it explains the color."""
    style = {"correct": ' style="success"', "present": "", "absent": ' style="danger"'}[state]
    return f'<tg-button type="callback_data"{style} data="wh:{state}:{letter}">{letter}</tg-button>'
