from bot.utils.text import clean_name, first_line, format_path, html


def test_clean_name_drops_emoji_and_extra_spaces() -> None:
    assert clean_name("  🧾 Kassa   ✅ ochish ▶️ ") == "Kassa ochish"
    assert clean_name("👨‍👩‍👧 Oila") == "Oila"


def test_clean_name_keeps_uzbek_letters_and_signs() -> None:
    assert clean_name("O‘quv qo‘llanma: ma’lumot № 2 (yangi)") == "O‘quv qo‘llanma: ma’lumot № 2 (yangi)"
    assert clean_name("Ўқув видео") == "Ўқув видео"


def test_clean_name_turns_line_breaks_into_spaces() -> None:
    assert clean_name("Birinchi\nikkinchi\tqator") == "Birinchi ikkinchi qator"


def test_first_line_skips_empty_lines() -> None:
    assert first_line("\n  \nNom\nTavsif") == "Nom"
    assert first_line(None) == ""


def test_format_path_keeps_short_paths() -> None:
    assert format_path(["Kassa", "Sozlash"]) == "Kassa › Sozlash"


def test_format_path_cuts_the_beginning_of_long_paths() -> None:
    titles = ["Birinchi uzun bo‘lim nomi", "Ikkinchi uzun bo‘lim nomi", "Uchinchi", "To‘rtinchi"]
    path = format_path(titles)
    assert len(path) <= 60
    assert path.startswith("… › ")
    assert path.endswith("Uchinchi › To‘rtinchi")


def test_html_escapes_markup() -> None:
    assert html("<b>A & B</b>") == "&lt;b&gt;A &amp; B&lt;/b&gt;"
