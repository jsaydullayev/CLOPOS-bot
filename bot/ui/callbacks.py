"""Button payloads. Each button carries its full state (at most 64 bytes),
so buttons keep working after the bot restarts."""

from aiogram.filters.callback_data import CallbackData

NOOP = "x"
ADMIN_PANEL = "ap"
CHANNEL_GUIDE = "ag"


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


class AdminIntroCb(CallbackData, prefix="ai"):
    """Editing a section's introduction (clear=True removes it)."""

    id: int
    clear: bool = False


class SectionCodesCb(CallbackData, prefix="ao"):
    """Section codes for channel captions."""

    page: int = 0


class AdminFlowCb(CallbackData, prefix="af"):
    """Buttons inside the step-by-step admin dialogs."""

    action: str  # cancel | dup | caption | skip | save
