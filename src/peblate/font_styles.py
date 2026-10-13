"""Font styles offered by the editor and language-creation wizard."""

SLOTS = (
    ("GOTHIC_14_EXTENDED", "Small text · 14 px"),
    ("GOTHIC_14_BOLD_EXTENDED", "Small bold text · 14 px"),
    ("GOTHIC_18_EXTENDED", "Body text · 18 px"),
    ("GOTHIC_18_BOLD_EXTENDED", "Body bold text · 18 px"),
    ("GOTHIC_24_EXTENDED", "Large text · 24 px"),
    ("GOTHIC_24_BOLD_EXTENDED", "Large bold text · 24 px"),
    ("GOTHIC_28_EXTENDED", "Heading · 28 px"),
    ("GOTHIC_28_BOLD_EXTENDED", "Bold heading · 28 px"),
    ("GOTHIC_36_EXTENDED", "Large heading · 36 px"),
    ("GOTHIC_36_BOLD_EXTENDED", "Large bold heading · 36 px"),
    ("LECO_20_BOLD_NUMBERS_EXTENDED", "LECO bold numbers and units · 20 px"),
    (
        "LECO_26_BOLD_NUMBERS_AM_PM_EXTENDED",
        "LECO bold numbers, units and AM/PM · 26 px",
    ),
    ("LECO_32_BOLD_NUMBERS_EXTENDED", "LECO bold numbers and units · 32 px"),
    ("LECO_36_BOLD_NUMBERS_EXTENDED", "LECO bold numbers and units · 36 px"),
    ("LECO_38_BOLD_NUMBERS_EXTENDED", "LECO bold numbers and units · 38 px"),
    ("LECO_42_NUMBERS_EXTENDED", "LECO numbers and units · 42 px"),
    ("LECO_28_LIGHT_NUMBERS_EXTENDED", "LECO light numbers and units · 28 px"),
    ("LECO_60_NUMBERS_AM_PM_EXTENDED", "LECO numbers, units and AM/PM · 60 px"),
    (
        "LECO_60_BOLD_NUMBERS_AM_PM_EXTENDED",
        "LECO bold numbers, units and AM/PM · 60 px",
    ),
)
TEXT_SLOTS = tuple(name for name, _ in SLOTS)
ALPHABET_SLOTS = tuple(name for name in TEXT_SLOTS if name.startswith("GOTHIC_"))
NUMBER_SLOTS = tuple(name for name in TEXT_SLOTS if name.startswith("LECO_"))


def base_font_path(slot):
    directory = "leco" if slot in NUMBER_SLOTS else "renderer"
    return "pebble/" + directory + "/" + slot.removesuffix("_EXTENDED") + ".pbf"
