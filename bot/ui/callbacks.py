"""Button payloads. Each button carries its full state (at most 64 bytes),
so buttons keep working after the bot restarts."""

from aiogram.filters.callback_data import CallbackData

NOOP = "x"
CONTACTS = "ct"
WRITE_PROBLEM = "pw"
CHANGE_PHONE = "pc"
ADMIN_PANEL = "ap"
CHANNEL_GUIDE = "ag"
ADMINS = "al"
ADD_ADMIN = "aa"
FIND_USER = "uf"
# The deep link from a ticket's card in the support channel: /start t<ticket id>.
TICKET_LINK = r"^t(\d{1,9})$"


class MenuCb(CallbackData, prefix="m"):
    page: int = 0


class CategoryCb(CallbackData, prefix="c"):
    id: int
    page: int = 0


class VideoCb(CallbackData, prefix="v"):
    id: int


class AdminCategoryCb(CallbackData, prefix="ac"):
    id: int = 0  # 0 = list of top-level categories
    page: int = 0  # negative = last page


class AdminNewCategoryCb(CallbackData, prefix="an"):
    parent: int = 0  # 0 = new top-level category


class AdminDeleteCategoryCb(CallbackData, prefix="ad"):
    id: int
    confirm: bool = False


class AdminPickCb(CallbackData, prefix="ak"):
    """Choosing where to add a video from the admin panel."""

    id: int = 0
    page: int = 0


class AdminAddVideoCb(CallbackData, prefix="av"):
    category: int


class AdminVideoCb(CallbackData, prefix="aw"):
    id: int


class AdminDeleteVideoCb(CallbackData, prefix="ax"):
    id: int
    confirm: bool = False


class AdminTextsCb(CallbackData, prefix="at"):
    """«Salomlashuv va matnlar»: the list (no key) or one text as the client sees it."""

    key: str = ""


class AdminTextEditCb(CallbackData, prefix="ae"):
    """Start changing a text (media=False) or its photo or video (media=True)."""

    key: str
    media: bool = False


class AdminTextResetCb(CallbackData, prefix="ar"):
    key: str
    media: bool = False  # True: remove only the photo or video


class AdminEmojiCb(CallbackData, prefix="ay"):
    """Setting a section's emoji (clear=True: back to the standard one)."""

    id: int
    clear: bool = False


class AdminIntroCb(CallbackData, prefix="ai"):
    """Editing a section's introduction (clear=True removes it)."""

    id: int
    clear: bool = False


class SectionCodesCb(CallbackData, prefix="ao"):
    """Section codes for channel captions."""

    page: int = 0


class AdminRemoveCb(CallbackData, prefix="au"):
    """Taking the admin rights away from a user added in the panel."""

    user_id: int
    confirm: bool = False


class SupportReportCb(CallbackData, prefix="sr"):
    """«📨 Murojaatlar»: the report of a day, days_ago before today."""

    days_ago: int = 0


class WaitingCb(CallbackData, prefix="sw"):
    """Tickets nobody has answered yet."""

    page: int = 0


class NotDoneCb(CallbackData, prefix="sn"):
    """Tickets marked «❌ Bajarilmadi», until they are marked done."""

    page: int = 0


class TicketCb(CallbackData, prefix="tk"):
    id: int


class TicketReplyCb(CallbackData, prefix="tr"):
    id: int


class TicketMarkCb(CallbackData, prefix="tm"):
    """Done or not done: in the support channel and in the bot."""

    id: int
    done: bool


class TicketFileCb(CallbackData, prefix="tf"):
    """The client's voice note, file or video message, which a screen cannot show."""

    id: int


class UsersCb(CallbackData, prefix="us"):
    page: int = 0


class UserCb(CallbackData, prefix="uc"):
    """One user's card; page: the list page to come back to."""

    id: int
    page: int = 0


class UserDeleteCb(CallbackData, prefix="ud"):
    id: int
    page: int = 0
    confirm: bool = False


class AdminFlowCb(CallbackData, prefix="af"):
    """Buttons inside the step-by-step admin dialogs."""

    action: str  # cancel | dup | caption | skip | save
