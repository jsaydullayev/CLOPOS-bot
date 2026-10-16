from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, MetaData, SmallInteger, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MEDIA_VIDEO = "video"
MEDIA_ANIMATION = "animation"
MEDIA_PHOTO = "photo"

# A ticket's way: new → answered (a reply was sent) → done or not done (marked by an admin).
TICKET_NEW = "new"
TICKET_ANSWERED = "answered"
TICKET_DONE = "done"
TICKET_NOT_DONE = "not_done"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    # Left with the first problem (+<digits>), offered again with the next ones.
    phone: Mapped[str | None] = mapped_column(String(16))
    # The single bot message the user navigates in (see TZ, section 6).
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Admin(Base):
    """An admin added in the admin panel. The owners in ADMIN_IDS (.env) are not stored here."""

    __tablename__ = "admins"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(String(255))  # as known when added
    added_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(40))
    # Shown before the title on the section's button; None: one by what the section holds.
    emoji: Mapped[str | None] = mapped_column(String(32))
    # Introduction the client sees under the title when entering the section (HTML).
    intro: Mapped[str | None] = mapped_column(Text)
    depth: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BotText(Base):
    """Interface texts the admin changed; a key without a row uses locales/uz.toml."""

    __tablename__ = "bot_texts"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)  # HTML, as Telegram formats it; None = standard text
    # A photo, video or animation shown with the text (the greeting only).
    media_file_id: Mapped[str | None] = mapped_column(Text)
    media_unique_id: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str | None] = mapped_column(String(16))  # MEDIA_PHOTO, MEDIA_VIDEO or MEDIA_ANIMATION
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Ticket(Base):
    """A problem a client left in «📞 Bog‘lanish va yordam», and how the admins dealt with it."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_name: Mapped[str] = mapped_column(String(255))  # as known when they wrote
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(16))  # to call the client back, as they left it
    text: Mapped[str | None] = mapped_column(Text)  # the message text or caption, as written
    media_type: Mapped[str | None] = mapped_column(String(16))  # photo, voice, document…; None: text only
    file_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=TICKET_NEW, index=True)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_by: Mapped[int | None] = mapped_column(BigInteger)  # the admin who replied last
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(BigInteger)
    # In the support channel: the copy of the client's message and the card under it with the buttons.
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    channel_copy_id: Mapped[int | None] = mapped_column(BigInteger)
    channel_card_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(300))
    # Telegram does not promise a maximum length for file_id.
    file_id: Mapped[str] = mapped_column(Text)
    file_unique_id: Mapped[str] = mapped_column(String(64), index=True)
    media_type: Mapped[str] = mapped_column(String(16), default=MEDIA_VIDEO)
    backup_message_id: Mapped[int | None] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
