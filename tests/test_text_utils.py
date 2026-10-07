from bot.utils.text import clean_name, first_line, format_path, html, name_key, typo_distance


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


def test_name_key_ignores_case_spaces_apostrophes_and_lookalike_letters() -> None:
    assert name_key("O‘quv  qo'llanma") == name_key("oʻquv qoʻllanma") == name_key("OQUV-QOLLANMA") == "oquvqollanma"
    assert name_key("Kassa") == name_key("Kаssа")  # Cyrillic а
    assert name_key("Ёлка") == name_key("елка")
    assert name_key("1-dars") != name_key("2-dars")


def test_typo_distance_counts_added_removed_replaced_and_swapped_letters() -> None:
    assert typo_distance("finans", "finans") == 0
    assert typo_distance("finas", "finans") == 1
    assert typo_distance("finanss", "finans") == 1
    assert typo_distance("fimans", "finans") == 1
    assert typo_distance("fianns", "finans") == 1  # neighbours swapped
    assert typo_distance("kassa", "ombor") == 5


def test_html_escapes_markup() -> None:
    assert html("<b>A & B</b>") == "&lt;b&gt;A &amp; B&lt;/b&gt;"
