"""Tickets: the card in the support channel and the admin's screens in the bot."""

from collections.abc import Sequence
from datetime import date
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import MEDIA_ANIMATION, MEDIA_PHOTO, MEDIA_VIDEO, TICKET_ANSWERED, TICKET_DONE, TICKET_NEW, Ticket
from bot.db.repo import TicketCounts
from bot.texts import t
from bot.ui.callbacks import (
    ADMIN_PANEL,
    SupportReportCb,
    TicketCb,
    TicketFileCb,
    TicketMarkCb,
    TicketReplyCb,
    WaitingCb,
)
from bot.ui.screen import (
    ACCENT_STYLE,
    BUTTON_STYLE,
    COLUMNS,
    Media,
    Screen,
    button,
    grid,
    keyboard,
    page_row,
    url_button,
    with_notice,
)
from bot.utils import clock
from bot.utils.phone import format_phone
from bot.utils.text import html, shorten

# A ticket on its screen fits a photo's caption: 1024 characters with the header and a notice.
TEXT_MAX = 500
NAME_MAX = 64
# Media a screen shows; anything else opens with «📎 Ilovani ochish».
SHOWN_MEDIA = (MEDIA_PHOTO, MEDIA_VIDEO, MEDIA_ANIMATION)
MEDIA_LABELS = {
    "photo": "ticket_media_photo",
    "video": "ticket_media_video",
    "animation": "ticket_media_animation",
    "voice": "ticket_media_voice",
    "audio": "ticket_media_audio",
    "document": "ticket_media_document",
    "video_note": "ticket_media_video_note",
}


def ticket_header(ticket: Ticket, names: dict[int, str], tz: ZoneInfo) -> str:
    """Number, who wrote and when, and where it stands."""
    who = html(shorten(ticket.user_name, NAME_MAX)) + (f" · @{html(ticket.username)}" if ticket.username else "")
    lines = [t("ticket_title", id=ticket.id), t("ticket_from", who=who, id=ticket.user_id)]
    if ticket.phone:
        lines.append(t("ticket_phone", phone=format_phone(ticket.phone)))
    lines += [t("ticket_time", time=clock.stamp(ticket.created_at, tz)), "", _status(ticket, names, tz)]
    return "\n".join(lines)


def channel_card(
    ticket: Ticket, names: dict[int, str], link: str, tz: ZoneInfo
) -> tuple[str, InlineKeyboardMarkup | None]:
    """The card under the client's message in the support channel."""
    rows = [
        [url_button(t("btn_ticket_answer"), link, style=ACCENT_STYLE)],
        _mark_row(ticket),
    ]
    return ticket_header(ticket, names, tz), keyboard(rows)


def ticket_screen(ticket: Ticket, names: dict[int, str], tz: ZoneInfo, notice: str | None = None) -> Screen:
    """The ticket in the bot: the client's message, an answer button and, once answered, the marks."""
    text = with_notice(ticket_header(ticket, names, tz) + _body(ticket), notice)
    if ticket.status == TICKET_NEW:
        rows = [[button(t("btn_ticket_write"), TicketReplyCb(id=ticket.id), style=ACCENT_STYLE)]]
    else:
        rows = [[button(t("btn_ticket_write_more"), TicketReplyCb(id=ticket.id))], _mark_row(ticket)]
    if ticket.media_type is not None and ticket.media_type not in SHOWN_MEDIA:
        rows.append([button(t("btn_ticket_file"), TicketFileCb(id=ticket.id))])
    rows.append([button(t("btn_waiting_short"), WaitingCb()), button(t("btn_report"), SupportReportCb())])
    if ticket.media_type in SHOWN_MEDIA and ticket.file_id is not None:
        return Screen(media=Media(ticket.file_id, ticket.media_type, text), markup=keyboard(rows))
    return Screen(text=text, markup=keyboard(rows))


def reply_prompt(ticket: Ticket, error: str | None = None) -> Screen:
    text = with_notice(t("reply_prompt", id=ticket.id, who=html(shorten(ticket.user_name, NAME_MAX))), error)
    return Screen(text=text, markup=keyboard([[button(t("btn_cancel"), TicketCb(id=ticket.id))]]))


def support_report(counts: TicketCounts, day: date, days_ago: int, waiting: int) -> Screen:
    """«📨 Murojaatlar»: one day's tickets, and everything still waiting for an answer."""
    when = t("report_today") if days_ago == 0 else t("report_yesterday") if days_ago == 1 else ""
    lines = [t("report_title", day=f"{day:%d.%m.%Y}", when=when).rstrip(), ""]
    if counts.total:
        lines += [
            t("report_total", total=counts.total, people=counts.people),
            t("report_replied", count=counts.replied),
            t("report_waiting", count=counts.waiting),
            t("report_marked", done=counts.done, not_done=counts.not_done),
        ]
    else:
        lines.append(t("report_none"))
    lines += ["", t("report_waiting_all", count=waiting) if waiting else t("report_all_answered")]

    style = ACCENT_STYLE if waiting else BUTTON_STYLE
    waiting_button = button(t("btn_waiting", count=waiting), WaitingCb(), style=style)
    days = [button(t("btn_day_before"), SupportReportCb(days_ago=days_ago + 1))]
    if days_ago:
        days.append(button(t("btn_day_after"), SupportReportCb(days_ago=days_ago - 1)))
    rows = [[waiting_button], days, [button(t("btn_admin_panel"), ADMIN_PANEL)]]
    return Screen(text="\n".join(lines), markup=keyboard(rows))


def waiting_screen(tickets: Sequence[Ticket], page: int, pages: int, total: int, tz: ZoneInfo, today: date) -> Screen:
    """Tickets nobody has answered, the oldest first; each opens to be answered."""
    if not tickets:
        text = t("waiting_none")
    else:
        lines = [t("waiting_title", count=total), t("waiting_hint"), ""]
        for ticket in tickets:
            lines.append(
                t(
                    "waiting_item",
                    id=ticket.id,
                    time=clock.short_stamp(ticket.created_at, tz, today),
                    who=html(shorten(ticket.user_name, 24)),
                    preview=html(_preview(ticket)),
                )
            )
        text = "\n".join(lines)
    buttons = [
        button(t("waiting_button", id=ticket.id, who=shorten(ticket.user_name, 16)), TicketCb(id=ticket.id))
        for ticket in tickets
    ]
    rows = grid(buttons, COLUMNS)
    rows.append(page_row(page, pages, lambda p: WaitingCb(page=p)))
    rows.append([button(t("btn_report"), SupportReportCb())])
    return Screen(text=text, markup=keyboard(rows))


def _status(ticket: Ticket, names: dict[int, str], tz: ZoneInfo) -> str:
    if ticket.status == TICKET_NEW:
        return t("ticket_status_new")
    if ticket.status == TICKET_ANSWERED:
        assert ticket.answered_at is not None and ticket.answered_by is not None
        return t(
            "ticket_status_answered",
            admin=_admin(names, ticket.answered_by),
            time=clock.stamp(ticket.answered_at, tz),
            replies=ticket.replies,
        )
    assert ticket.resolved_at is not None and ticket.resolved_by is not None
    key = "ticket_status_done" if ticket.status == TICKET_DONE else "ticket_status_not_done"
    return t(key, admin=_admin(names, ticket.resolved_by), time=clock.stamp(ticket.resolved_at, tz))


def _admin(names: dict[int, str], user_id: int) -> str:
    return html(names.get(user_id) or t("admin_name_id", id=user_id))


def _mark_row(ticket: Ticket) -> list[InlineKeyboardButton]:
    return [
        button(t("btn_ticket_done"), TicketMarkCb(id=ticket.id, done=True)),
        button(t("btn_ticket_not_done"), TicketMarkCb(id=ticket.id, done=False)),
    ]


def _body(ticket: Ticket) -> str:
    """What the client wrote: the kind of attachment and the text."""
    parts = []
    if ticket.media_type is not None:
        parts.append(t(MEDIA_LABELS[ticket.media_type]))
    if ticket.text:
        parts.append(t("ticket_text", text=html(shorten(ticket.text, TEXT_MAX))))
    return "\n\n" + "\n".join(parts) if parts else ""


def _preview(ticket: Ticket) -> str:
    if ticket.text:
        return shorten(ticket.text, 50, one_line=True)
    return t(MEDIA_LABELS[ticket.media_type]) if ticket.media_type is not None else ""
