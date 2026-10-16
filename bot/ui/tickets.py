"""Tickets: the card in the support channel and the admin's screens in the bot."""

from collections.abc import Sequence
from datetime import date
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import (
    MEDIA_ANIMATION,
    MEDIA_PHOTO,
    MEDIA_VIDEO,
    TICKET_ANSWERED,
    TICKET_DONE,
    TICKET_NEW,
    TICKET_NOT_DONE,
    Ticket,
)
from bot.db.repo import TicketCounts
from bot.texts import t
from bot.ui.callbacks import (
    ADMIN_PANEL,
    NotDoneCb,
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
    DANGER_STYLE,
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

# The client's text on the ticket's screen: under a photo it fits the caption (1024 characters with
# the header and a notice); a text ticket shows it whole, as a message holds 4096.
CAPTION_TEXT_MAX = 500
MESSAGE_TEXT_MAX = 3500
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
    with_media = ticket.media_type in SHOWN_MEDIA and ticket.file_id is not None
    body = _body(ticket, CAPTION_TEXT_MAX if with_media else MESSAGE_TEXT_MAX)
    text = with_notice(ticket_header(ticket, names, tz) + body, notice)
    if ticket.status == TICKET_NEW:
        rows = [[button(t("btn_ticket_write"), TicketReplyCb(id=ticket.id), style=ACCENT_STYLE)]]
    else:
        rows = [[button(t("btn_ticket_write_more"), TicketReplyCb(id=ticket.id))], _mark_row(ticket)]
    if ticket.media_type is not None and ticket.media_type not in SHOWN_MEDIA:
        rows.append([button(t("btn_ticket_file"), TicketFileCb(id=ticket.id))])
    # Back to the list the ticket is in.
    if ticket.status == TICKET_NOT_DONE:
        back = button(t("btn_not_done_short"), NotDoneCb())
    else:
        back = button(t("btn_waiting_short"), WaitingCb())
    rows.append([back, button(t("btn_report"), SupportReportCb())])
    if with_media:
        assert ticket.media_type is not None and ticket.file_id is not None
        return Screen(media=Media(ticket.file_id, ticket.media_type, text), markup=keyboard(rows))
    return Screen(text=text, markup=keyboard(rows))


def reply_prompt(ticket: Ticket, error: str | None = None) -> Screen:
    text = with_notice(t("reply_prompt", id=ticket.id, who=html(shorten(ticket.user_name, NAME_MAX))), error)
    return Screen(text=text, markup=keyboard([[button(t("btn_cancel"), TicketCb(id=ticket.id))]]))


def support_report(counts: TicketCounts, day: date, days_ago: int, waiting: int, not_done: int) -> Screen:
    """«📨 Murojaatlar»: one day's tickets, and of all days the ones waiting for an answer and not done."""
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
    if not_done:
        lines.append(t("report_not_done_all", count=not_done))

    waiting_style = ACCENT_STYLE if waiting else BUTTON_STYLE
    not_done_style = DANGER_STYLE if not_done else BUTTON_STYLE
    days = [button(t("btn_day_before"), SupportReportCb(days_ago=days_ago + 1))]
    if days_ago:
        days.append(button(t("btn_day_after"), SupportReportCb(days_ago=days_ago - 1)))
    rows = [
        [button(t("btn_waiting", count=waiting), WaitingCb(), style=waiting_style)],
        [button(t("btn_not_done", count=not_done), NotDoneCb(), style=not_done_style)],
        days,
        [button(t("btn_admin_panel"), ADMIN_PANEL)],
    ]
    return Screen(text="\n".join(lines), markup=keyboard(rows))


def waiting_screen(tickets: Sequence[Ticket], page: int, pages: int, total: int, tz: ZoneInfo, today: date) -> Screen:
    """Tickets nobody has answered, the oldest first; each opens to be answered."""
    title = t("waiting_title", count=total) + "\n" + t("waiting_hint")
    items = [_list_item(ticket, tz, today) for ticket in tickets]
    return _ticket_list(tickets, items, page, pages, WaitingCb, title=title, empty=t("waiting_none"))


def not_done_screen(
    tickets: Sequence[Ticket], names: dict[int, str], page: int, pages: int, total: int, tz: ZoneInfo, today: date
) -> Screen:
    """Tickets marked «❌ Bajarilmadi», the oldest first: who marked them, and whether the client got
    another answer since. Each opens to be answered again; a ticket leaves the list once marked done."""
    title = t("not_done_title", count=total) + "\n" + t("not_done_hint")
    items = []
    for ticket in tickets:
        assert ticket.resolved_at is not None and ticket.resolved_by is not None
        when = clock.short_stamp(ticket.resolved_at, tz, today)
        mark = t("not_done_mark", admin=_admin(names, ticket.resolved_by), time=when)
        if _answered_again(ticket):
            mark += t("not_done_answered_again")
        items.append(_list_item(ticket, tz, today) + "\n" + mark)
    return _ticket_list(tickets, items, page, pages, NotDoneCb, title=title, empty=t("not_done_none"))


def _ticket_list(
    tickets: Sequence[Ticket],
    items: Sequence[str],
    page: int,
    pages: int,
    list_cb: type[WaitingCb] | type[NotDoneCb],
    *,
    title: str,
    empty: str,
) -> Screen:
    """A page of tickets: a line or two on each in the text, and a button that opens it."""
    text = title + "\n\n" + "\n".join(items) if tickets else empty
    buttons = [
        button(t("waiting_button", id=ticket.id, who=shorten(ticket.user_name, 16)), TicketCb(id=ticket.id))
        for ticket in tickets
    ]
    rows = grid(buttons, COLUMNS)
    rows.append(page_row(page, pages, lambda p: list_cb(page=p)))
    rows.append([button(t("btn_report"), SupportReportCb())])
    return Screen(text=text, markup=keyboard(rows))


def _list_item(ticket: Ticket, tz: ZoneInfo, today: date) -> str:
    return t(
        "waiting_item",
        id=ticket.id,
        time=clock.short_stamp(ticket.created_at, tz, today),
        who=html(shorten(ticket.user_name, 24)),
        preview=html(_preview(ticket)),
    )


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
    status = t(key, admin=_admin(names, ticket.resolved_by), time=clock.stamp(ticket.resolved_at, tz))
    if _answered_again(ticket):
        assert ticket.answered_at is not None and ticket.answered_by is not None
        when = clock.stamp(ticket.answered_at, tz)
        status += "\n" + t("ticket_answered_again", admin=_admin(names, ticket.answered_by), time=when)
    return status


def _answered_again(ticket: Ticket) -> bool:
    """The client got another answer after the ticket was marked."""
    if ticket.answered_at is None or ticket.resolved_at is None:
        return False
    return clock.as_utc(ticket.answered_at) > clock.as_utc(ticket.resolved_at)


def _admin(names: dict[int, str], user_id: int) -> str:
    return html(names.get(user_id) or t("admin_name_id", id=user_id))


def _mark_row(ticket: Ticket) -> list[InlineKeyboardButton]:
    return [
        button(t("btn_ticket_done"), TicketMarkCb(id=ticket.id, done=True)),
        button(t("btn_ticket_not_done"), TicketMarkCb(id=ticket.id, done=False)),
    ]


def _body(ticket: Ticket, text_max: int) -> str:
    """What the client wrote: the kind of attachment and the text."""
    parts = []
    if ticket.media_type is not None:
        parts.append(t(MEDIA_LABELS[ticket.media_type]))
    if ticket.text:
        parts.append(t("ticket_text", text=html(shorten(ticket.text, text_max))))
    return "\n\n" + "\n".join(parts) if parts else ""


def _preview(ticket: Ticket) -> str:
    if ticket.text:
        return shorten(ticket.text, 50, one_line=True)
    return t(MEDIA_LABELS[ticket.media_type]) if ticket.media_type is not None else ""
