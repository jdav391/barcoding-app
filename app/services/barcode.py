from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
from pylibdmtx.pylibdmtx import encode as dmtx_encode


@dataclass
class SheetBarcode:
    doc_index: int
    sheet_number: int
    barcode_string: str
    is_overflow: bool
    page_index: int


def generate_barcode_string(
    unique_id: int,
    sheet_number: int,
    set_count: int,
    has_insert: bool,
    is_end_of_group: bool,
    divert: bool | None = None,
) -> str:
    """Generate a 13- or 14-character barcode string.

    Format (standard, 13 chars):
        {EOG}{Sheet#}{Insert}{SetCount}{UniqueID(9)}

    Format (extended with divert, 14 chars):
        {EOG}{Sheet#}{Insert}{SetCount}{Divert}{UniqueID(9)}

    - EOG       : 1 if is_end_of_group else 0
    - Sheet#    : integer 1-9
    - Insert    : 1 if has_insert else 0
    - SetCount  : integer 1-9
    - Divert    : 1 if divert else 0 (only present when divert is not None)
    - UniqueID  : 9-digit zero-padded; if unique_id has more than 9 digits,
                  the last 9 digits are used.
    """
    eog = "1" if is_end_of_group else "0"
    sheet = str(sheet_number)
    insert = "1" if has_insert else "0"
    count = str(set_count)

    # Unique ID: take last 9 digits (mod 10^9), zero-padded to 9 places
    uid = str(unique_id % (10 ** 9)).zfill(9)

    if divert is None:
        return f"{eog}{sheet}{insert}{count}{uid}"
    else:
        div = "1" if divert else "0"
        return f"{eog}{sheet}{insert}{count}{div}{uid}"


def generate_barcode_image(
    barcode_string: str,
    module_size_mm: float = 0.50,
    quiet_zone_mm: float = 6.5,
    dpi: int = 600,
) -> Image.Image:
    pixels_per_mm = dpi / 25.4
    module_px = round(module_size_mm * pixels_per_mm)
    quiet_zone_px = round(quiet_zone_mm * pixels_per_mm)

    encoded = dmtx_encode(barcode_string.encode("ascii"), size="18x18")
    raw = Image.frombytes("RGB", (encoded.width, encoded.height), encoded.pixels)

    symbol_px = 18 * module_px
    scaled = raw.resize((symbol_px, symbol_px), Image.NEAREST)

    total_px = symbol_px + 2 * quiet_zone_px
    final = Image.new("RGB", (total_px, total_px), "white")
    final.paste(scaled, (quiet_zone_px, quiet_zone_px))

    return final


def validate_barcode_string(barcode_string: str) -> bool:
    """Validate a barcode string.

    Returns True if the string is a valid 13- or 14-character barcode, False otherwise.

    Rules:
    - Must be 13 or 14 characters long
    - Must be entirely numeric
    - Position 1 (EOG): must be 0 or 1
    - Position 2 (Sheet#): must be 1-9
    - Position 3 (Insert): must be 0 or 1
    - Position 4 (SetCount): must be 1-9
    - Position 5 (Divert, only for 14-char): must be 0 or 1
    """
    length = len(barcode_string)
    if length not in (13, 14):
        return False

    if not barcode_string.isdigit():
        return False

    eog = barcode_string[0]
    sheet = barcode_string[1]
    insert = barcode_string[2]
    set_count = barcode_string[3]

    if eog not in ("0", "1"):
        return False

    if sheet not in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        return False

    if insert not in ("0", "1"):
        return False

    if set_count not in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        return False

    if length == 14:
        divert = barcode_string[4]
        if divert not in ("0", "1"):
            return False

    return True
