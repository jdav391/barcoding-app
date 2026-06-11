from PIL import Image

from app.services.barcode import generate_barcode_image, generate_barcode_string, validate_barcode_string


class TestGenerateBarcodeString:
    def test_standard_13_char(self):
        result = generate_barcode_string(unique_id=158404144, sheet_number=3, set_count=7, insert_count=0, is_end_of_group=False)
        assert result == "0307158404144"
        assert len(result) == 13

    def test_end_of_group(self):
        result = generate_barcode_string(unique_id=158404144, sheet_number=7, set_count=7, insert_count=0, is_end_of_group=True)
        assert result == "1707158404144"

    def test_with_insert(self):
        result = generate_barcode_string(unique_id=158404144, sheet_number=1, set_count=1, insert_count=1, is_end_of_group=True)
        assert result == "1111158404144"

    def test_unique_id_zero_padded(self):
        result = generate_barcode_string(unique_id=42, sheet_number=1, set_count=1, insert_count=0, is_end_of_group=True)
        assert result == "1101000000042"

    def test_unique_id_truncated_to_9_digits(self):
        result = generate_barcode_string(unique_id=1234567890, sheet_number=1, set_count=1, insert_count=0, is_end_of_group=True)
        assert result == "1101234567890"
        assert len(result) == 13

    def test_with_divert_14_char(self):
        result = generate_barcode_string(unique_id=158404144, sheet_number=3, set_count=7, insert_count=0, is_end_of_group=False, divert=True)
        assert result == "03071158404144"
        assert len(result) == 14

    def test_divert_false_14_char(self):
        result = generate_barcode_string(unique_id=158404144, sheet_number=3, set_count=7, insert_count=0, is_end_of_group=False, divert=False)
        assert result == "03070158404144"
        assert len(result) == 14

    def test_single_sheet_is_eog(self):
        result = generate_barcode_string(unique_id=1, sheet_number=1, set_count=1, insert_count=0, is_end_of_group=True)
        assert result == "1101000000001"


class TestGenerateBarcodeImage:
    def test_generates_pil_image(self):
        img = generate_barcode_image("0307158404144")
        assert isinstance(img, Image.Image)

    def test_default_dimensions_600dpi(self):
        img = generate_barcode_image("0307158404144", module_size_mm=0.50, quiet_zone_mm=6.5, dpi=600)
        module_px = round(0.50 * 600 / 25.4)
        symbol_px = 18 * module_px
        quiet_px = round(6.5 * 600 / 25.4)
        total_px = symbol_px + 2 * quiet_px
        assert img.width == total_px
        assert img.height == total_px

    def test_black_on_white(self):
        img = generate_barcode_image("0307158404144").convert("L")
        corners = [img.getpixel((0, 0)), img.getpixel((img.width - 1, 0))]
        assert all(c > 200 for c in corners), "Quiet zone corners should be white"

    def test_14_char_barcode(self):
        img = generate_barcode_image("03071158404144")
        assert isinstance(img, Image.Image)


class TestValidateBarcodeString:
    def test_valid_13_char(self):
        assert validate_barcode_string("0307158404144") is True

    def test_valid_14_char(self):
        assert validate_barcode_string("03071158404144") is True

    def test_wrong_length(self):
        assert validate_barcode_string("030715840414") is False
        assert validate_barcode_string("030715840414400") is False

    def test_non_numeric(self):
        assert validate_barcode_string("030715840414A") is False

    def test_invalid_eog(self):
        assert validate_barcode_string("2307158404144") is False

    def test_invalid_sheet_zero(self):
        assert validate_barcode_string("0007158404144") is False

    def test_insert_pockets_0_to_4_valid(self):
        for ch in "01234":
            assert validate_barcode_string(f"03{ch}7158404144") is True

    def test_invalid_insert_above_four(self):
        assert validate_barcode_string("0357158404144") is False
        assert validate_barcode_string("0397158404144") is False

    def test_invalid_set_count_zero(self):
        assert validate_barcode_string("0300158404144") is False

    def test_invalid_divert_in_14_char(self):
        assert validate_barcode_string("03072158404144") is False
