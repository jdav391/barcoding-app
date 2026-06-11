from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
from pylibdmtx.pylibdmtx import encode as dmtx_encode

# Single-digit positional fields cap both values at 9. Exceeding this would
# shift every downstream position in the payload, so it is a hard error.
MAX_SHEET_NUMBER = 9
MAX_SET_COUNT = 9

# All payloads fit an 18x18 ECC200 symbol (36 numeric digit capacity)
DM_MODULES = 18


class BarcodePayloadError(ValueError):
    """A field value cannot be represented in the positional barcode format."""


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

    Raises BarcodePayloadError if any field is out of range for its
    single-character position.
    """
    if not 1 <= sheet_number <= MAX_SHEET_NUMBER:
        raise BarcodePayloadError(
            f"sheet_number {sheet_number} out of range 1-{MAX_SHEET_NUMBER}"
        )
    if not 1 <= set_count <= MAX_SET_COUNT:
        raise BarcodePayloadError(
            f"set_count {set_count} out of range 1-{MAX_SET_COUNT}"
        )
    if sheet_number > set_count:
        raise BarcodePayloadError(
            f"sheet_number {sheet_number} exceeds set_count {set_count}"
        )
    if unique_id < 0:
        raise BarcodePayloadError(f"unique_id must be non-negative, got {unique_id}")

    eog = "1" if is_end_of_group else "0"
    sheet = str(sheet_number)
    insert = "1" if has_insert else "0"
    count = str(set_count)

    # Unique ID: take last 9 digits (mod 10^9), zero-padded to 9 places
    uid = str(unique_id % (10 ** 9)).zfill(9)

    if divert is None:
        barcode = f"{eog}{sheet}{insert}{count}{uid}"
    else:
        div = "1" if divert else "0"
        barcode = f"{eog}{sheet}{insert}{count}{div}{uid}"

    if not validate_barcode_string(barcode):
        raise BarcodePayloadError(f"generated barcode failed validation: {barcode!r}")
    return barcode


def _encode_dmtx(barcode_string: str) -> Image.Image:
    """Encode the payload as an 18x18 ECC200 symbol; return the raw raster."""
    try:
        encoded = dmtx_encode(barcode_string.encode("ascii"), size="18x18")
    except Exception as e:
        raise BarcodePayloadError(
            f"Data Matrix encoding failed for {barcode_string!r} "
            f"(18x18 symbol): {e}"
        ) from e
    if encoded is None:
        raise BarcodePayloadError(
            f"Data Matrix encoding returned no symbol for {barcode_string!r} "
            f"— payload may exceed 18x18 capacity"
        )
    return Image.frombytes("RGB", (encoded.width, encoded.height), encoded.pixels)


def dmtx_module_matrix(barcode_string: str) -> list[list[bool]]:
    """Return the 18x18 module grid (True = dark), row 0 = top row.

    The symbol is located inside libdmtx's raster by the bounding box of its
    dark pixels, then each module is sampled at its center. The result is
    verified against the ECC200 finder pattern (solid left column and bottom
    row) so a sampling error can never silently produce a wrong symbol.
    """
    from PIL import ImageOps

    gray = _encode_dmtx(barcode_string).convert("L")
    bbox = ImageOps.invert(gray).getbbox()
    if bbox is None:
        raise BarcodePayloadError(
            f"Data Matrix raster for {barcode_string!r} contains no dark pixels"
        )
    left, top, right, bottom = bbox
    module_w = (right - left) / DM_MODULES
    module_h = (bottom - top) / DM_MODULES

    matrix: list[list[bool]] = []
    for row in range(DM_MODULES):
        cy = int(top + (row + 0.5) * module_h)
        matrix.append([
            gray.getpixel((int(left + (col + 0.5) * module_w), cy)) < 128
            for col in range(DM_MODULES)
        ])

    # ECC200 finder pattern: left column and bottom row are solid dark
    if not all(matrix[r][0] for r in range(DM_MODULES)) or not all(matrix[-1]):
        raise BarcodePayloadError(
            f"Sampled Data Matrix grid for {barcode_string!r} failed the "
            f"finder-pattern check — refusing to render an unverified symbol"
        )
    return matrix


def generate_barcode_image(
    barcode_string: str,
    module_size_mm: float = 0.50,
    quiet_zone_mm: float = 6.5,
    dpi: int = 600,
) -> Image.Image:
    pixels_per_mm = dpi / 25.4
    module_px = round(module_size_mm * pixels_per_mm)
    quiet_zone_px = round(quiet_zone_mm * pixels_per_mm)

    from PIL import ImageOps

    raw = _encode_dmtx(barcode_string)
    # Crop libdmtx's internal margin away first — resizing the full raster
    # (symbol + margin) would shrink the printed module size below spec.
    bbox = ImageOps.invert(raw.convert("L")).getbbox()
    if bbox:
        raw = raw.crop(bbox)

    symbol_px = DM_MODULES * module_px
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
