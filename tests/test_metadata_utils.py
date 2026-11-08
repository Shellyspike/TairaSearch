from __future__ import annotations

import unittest

from metadata_utils import classify_text_quality


class TextQualityTests(unittest.TestCase):
    def test_type_one_glyph_stream_is_garbled(self) -> None:
        text = "Предисловие /TypeOne47/TypeOne48/TypeOne49 основной текст"

        self.assertEqual(classify_text_quality(text), "garbled")

    def test_single_type_one_reference_does_not_reject_readable_text(self) -> None:
        text = "Readable discussion of the /TypeOne47 font mapping."

        self.assertEqual(classify_text_quality(text), "good")

    def test_many_unrelated_scripts_signal_broken_font_mapping(self) -> None:
        text = (
            "ɹɹ Ӵ α अ Ґ த ক ོ ҡ ࢿ ۙ " * 4
            + "ordinary Latin context " * 4
        )

        self.assertEqual(classify_text_quality(text), "garbled")

    def test_normal_japanese_with_latin_terms_remains_good(self) -> None:
        text = "平家物語とGenpei jōsuikiの比較研究。熊谷直実の物語を検討する。"

        self.assertEqual(classify_text_quality(text), "good")


if __name__ == "__main__":
    unittest.main()
