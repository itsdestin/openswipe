# SPDX-FileCopyrightText: 2026 Destin Moss <https://youcoded.ai>
#
# SPDX-License-Identifier: MIT

"""Language hooks preserve each stock layout and fail closed transactionally on drift."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
# REUSE-IgnoreStart (a stock layout's header, as test data: not this file's licence)
STOCK = '''// SPDX-License-Identifier: GPL-3.0-only
import QtQuick
import QtQuick.VirtualKeyboard
KeyboardLayout {
    inputMode: InputEngine.InputMode.Latin
    Key { key: Qt.Key_Q; text: "q" }
    SpaceKey {}
}
'''
# REUSE-IgnoreEnd
# REUSE-IgnoreStart (a stock layout's letter row, as test data: not this file's licence)
LETTERS = '''// SPDX-License-Identifier: GPL-3.0-only
import QtQuick
import QtQuick.VirtualKeyboard
KeyboardLayout {
    inputMode: InputEngine.InputMode.Latin
    KeyboardRow {
        Key {
            key: Qt.Key_A
            text: "a"
            alternativeKeys: "aäåãâàá"
        }
        Key {
            key: Qt.Key_F
            text: "f"
        }
        Key {
            key: Qt.Key_Z
            text: "z"
            alternativeKeys: "zžż"
        }
        Key {
            id: normalKey
            key: Qt.Key_Q
            text: "q"
            alternativeKeys: "q1"
            smallText: "1"
            smallTextVisible: true
        }
        Key {
            key: Qt.Key_Period
            weight: normalKeyWidth
            Layout.fillWidth: false
            text: "."
            alternativeKeys: "!.?"
            smallText: "!?"
            smallTextVisible: true
            highlighted: true
        }
    }
    SpaceKey {}
}
'''
# REUSE-IgnoreEnd


def load_module(name):
    path = ROOT / 'integration' / (name + '.py')
    if not path.is_file():
        raise AssertionError(f'Missing standalone integration: {path.name}')
    spec = importlib.util.spec_from_file_location('swipe_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.layout = load_module('layout')

    def patch_as_prepare_overrides_would(self, source, locale):
        """Mirrors prepare_overrides' own per-locale logic, for tests that assert an exact byte match."""
        patched = self.layout.patch_english(source)
        if locale.startswith('en'):
            patched = self.layout.add_symbol_hints(patched)
            patched = self.layout.add_period_symbols(patched)
        return patched

    def test_injects_listener_without_rearranging_keys(self):
        result = self.layout.patch_english(STOCK)
        self.assertIn('Key { key: Qt.Key_Q; text: "q" }', result)
        self.assertIn('SpaceKey {}', result)
        self.assertIn('createInputMethod()', result)
        self.assertIn('SwipeCapture', result)
        self.assertIn('id: swipeLayout', result)
        # REUSE-IgnoreStart
        self.assertTrue(result.startswith('// SPDX-License-Identifier: GPL-3.0-only'))
        # REUSE-IgnoreEnd

    def test_refuses_unknown_or_already_customised_layout(self):
        for source in ('Item {}', STOCK.replace('SpaceKey {}', ''),
                       STOCK.replace('KeyboardLayout {', 'KeyboardLayout {\n id: custom'),
                       STOCK.replace('SpaceKey {}', 'SpaceKey {}\n Component.onCompleted: {}')):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    self.layout.patch_english(source)

    def test_builds_only_present_approved_overrides_and_keeps_other_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
            (src / 'fallback').mkdir(parents=True)
            (src / 'fallback/main.qml').write_text(STOCK)
            (src / 'en_US').mkdir()
            (src / 'en_US/main.fallback').write_text('')
            (src / 'en_US/symbols.fallback').write_text('')
            (src / 'pt_BR').mkdir()
            (src / 'pt_BR/main.qml').write_text('PORTUGUESE UNCHANGED')
            self.layout.build_overlay(src, dst)
            self.assertIn('SwipeCapture', (dst / 'en_US/main.qml').read_text())
            self.assertEqual((dst / 'fallback/main.qml').read_text(), STOCK)
            self.assertEqual((dst / 'pt_BR/main.qml').read_text(), 'PORTUGUESE UNCHANGED')
            self.assertEqual((dst / 'en_US/symbols.fallback').read_text(), '')
            self.assertEqual((src / 'en_US/main.fallback').read_text(), '')

    def test_hooks_approved_locales_without_changing_physical_stock_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
            sources = {}
            for locale, glyph in (('en_US', 'q'), ('en_GB', '£'), ('es_ES', 'ñ'),
                                  ('es_MX', 'á'), ('fr_FR', 'a'), ('fr_CA', 'ç'),
                                  ('de_DE', 'z'), ('de_AT', 'ü'), ('es', 'í')):
                folder = src / locale
                folder.mkdir(parents=True)
                source = STOCK.replace('text: "q"', f'text: "{glyph}"; alternativeKeys: "{glyph}éß"')
                source = source.replace('    Key {', f'    // physical {locale}\n    Key {{')
                (folder / 'main.qml').write_text(source)
                (folder / 'symbols.fallback').write_text('')
                sources[locale] = source
            for locale in ('en_AU', 'pt_BR', 'it_IT'):
                (src / locale).mkdir()
                (src / locale / 'main.qml').write_text('untargeted custom layout')
            before = {p.relative_to(src): p.read_bytes() for p in src.rglob('*') if p.is_file()}
            self.layout.build_overlay(src, dst)
            for locale, source in sources.items():
                with self.subTest(locale=locale):
                    result = (dst / locale / 'main.qml').read_text()
                    self.assertEqual(result, self.patch_as_prepare_overrides_would(source, locale))
                    self.assertIn('SwipeInputMethod {}', result)
                    self.assertEqual((dst / locale / 'symbols.fallback').read_text(), '')
                    self.assertNotIn('en_US', result if locale != 'en_US' else '')
                    self.assertNotIn('English-only', result)
            for locale in ('en_AU', 'pt_BR', 'it_IT'):
                self.assertEqual((dst / locale / 'main.qml').read_text(), 'untargeted custom layout')
            self.assertEqual(before, {p.relative_to(src): p.read_bytes() for p in src.rglob('*') if p.is_file()})

    def test_each_empty_fallback_marker_uses_stock_fallback_not_us_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
            (src / 'fallback').mkdir(parents=True)
            fallback = STOCK.replace('text: "q"', 'text: "fallback geometry"')
            (src / 'fallback/main.qml').write_text(fallback)
            (src / 'en_US').mkdir()
            (src / 'en_US/main.qml').write_text(STOCK.replace('text: "q"', 'text: "US geometry"'))
            for locale in ('en_GB', 'es_AR', 'fr_BE', 'de_CH'):
                (src / locale).mkdir()
                (src / locale / 'main.fallback').write_text('')
            self.layout.build_overlay(src, dst)
            for locale in ('en_GB', 'es_AR', 'fr_BE', 'de_CH'):
                with self.subTest(locale=locale):
                    self.assertEqual((dst / locale / 'main.qml').read_text(),
                                    self.patch_as_prepare_overrides_would(fallback, locale))
                    self.assertFalse((dst / locale / 'main.fallback').exists())
                    self.assertEqual((src / locale / 'main.fallback').read_text(), '')
            self.assertEqual((dst / 'fallback/main.qml').read_text(), fallback)
            self.assertFalse((dst / 'fr_FR').exists())  # Never synthesize absent locale directories.

    def test_invalid_target_locale_does_not_publish_any_partial_overlay(self):
        for bad in ('Item {}', STOCK.replace('KeyboardLayout {', 'KeyboardLayout {\n id: custom'),
                    STOCK.replace('SpaceKey {}', 'SpaceKey {}\n Component.onCompleted: {}')):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
                for locale, source in (('en_US', STOCK), ('es_ES', STOCK), ('fr_FR', bad)):
                    (src / locale).mkdir(parents=True)
                    (src / locale / 'main.qml').write_text(source)
                dst.mkdir()
                (dst / 'precious').write_text('keep')
                with self.assertRaises(ValueError):
                    self.layout.build_overlay(src, dst)
                self.assertEqual(list(dst.iterdir()), [dst / 'precious'])
                self.assertEqual((dst / 'precious').read_text(), 'keep')
                self.assertFalse(dst.with_name('overlay.previous').exists())
                self.assertFalse(list(dst.parent.glob('.layouts-*')))

    def test_nonempty_or_missing_target_fallback_is_never_guessed(self):
        for marker in ('fr_FR', None):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
                (src / 'en_US').mkdir(parents=True)
                (src / 'en_US/main.qml').write_text(STOCK)
                (src / 'fr_CA').mkdir()
                (src / 'fr_FR').mkdir()
                (src / 'fr_FR/main.qml').write_text(STOCK)
                if marker is not None:
                    (src / 'fr_CA/main.fallback').write_text(marker)
                with self.assertRaises(ValueError):
                    self.layout.build_overlay(src, dst)
                self.assertFalse(dst.exists())

    def test_rename_failure_rolls_back_complete_previous_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
            for locale in ('en_US', 'en_GB', 'es_ES', 'fr_FR', 'de_DE'):
                (src / locale).mkdir(parents=True)
                (src / locale / 'main.qml').write_text(STOCK)
            dst.mkdir()
            (dst / 'previous-content').write_text('keep')
            original = Path.rename
            def fail_publish(path, target):
                if path.name == 'layouts' and Path(target) == dst:
                    raise OSError('simulated staged rename failure')
                return original(path, target)
            with mock.patch.object(Path, 'rename', fail_publish):
                with self.assertRaisesRegex(OSError, 'staged rename'):
                    self.layout.build_overlay(src, dst)
            self.assertEqual(list(dst.iterdir()), [dst / 'previous-content'])
            self.assertEqual((dst / 'previous-content').read_text(), 'keep')
            self.assertFalse(dst.with_name('overlay.previous').exists())

    def test_nested_or_malformed_custom_root_is_not_patched(self):
        for source in ('Item {\n' + STOCK + '\n}', STOCK + '\nItem {}',
                       STOCK.replace('    SpaceKey {}', '    SpaceKey {'),
                       STOCK.replace('    SpaceKey {}', '    SpaceKey {}\n id: custom'),
                       STOCK.replace('    SpaceKey {}', '    SpaceKey {}\n inputMethod: custom')):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.layout.patch_english(source)

    def test_symbol_hint_prepended_ahead_of_existing_accents(self):
        result = self.layout.add_symbol_hints(LETTERS)
        self.assertIn('alternativeKeys: "@aäåãâàá"', result)
        self.assertIn('alternativeKeys: "*zžż"', result)

    def test_symbol_hint_added_for_a_letter_with_no_existing_alternatives(self):
        result = self.layout.add_symbol_hints(LETTERS)
        self.assertIn('alternativeKeys: "_f"', result)

    def test_symbol_hint_escaped_quote_is_valid_qml(self):
        source = LETTERS.replace('key: Qt.Key_F', 'key: Qt.Key_X').replace('text: "f"', 'text: "x"')
        result = self.layout.add_symbol_hints(source)
        self.assertIn('alternativeKeys: "\\"x"', result)
        self.assertIn('smallText: "\\""', result)  # corner hint gets the same escaped quote

    def test_symbol_hints_never_touch_untargeted_letters_or_other_keys(self):
        result = self.layout.add_symbol_hints(LETTERS)
        self.assertIn('SpaceKey {}', result)
        self.assertNotIn('Qt.Key_W', result)  # fixture has none; guards against an over-eager match

    def test_symbol_hint_braces_do_not_confuse_key_block_boundaries(self):
        # O and P's own symbols are literal "{" and "}" — a naive brace counter would mistake a
        # value like alternativeKeys: "{..." for real QML structure and corrupt every key after it.
        source = (LETTERS.replace('key: Qt.Key_A', 'key: Qt.Key_O').replace('text: "a"', 'text: "o"')
                         .replace('key: Qt.Key_Z', 'key: Qt.Key_P').replace('text: "z"', 'text: "p"'))
        result = self.layout.add_symbol_hints(source)
        self.assertIn('alternativeKeys: "{aäåãâàá"', result)
        self.assertIn('alternativeKeys: "}zžż"', result)
        self.assertIn('smallText: "{"', result)
        self.assertIn('smallText: "}"', result)
        self.assertIn('SpaceKey {}', result)  # the rest of the document must still parse structurally intact
        self.assertTrue(result.rstrip().endswith('}'))  # the KeyboardLayout root still closes correctly

    def test_symbol_hints_missing_letter_is_left_alone_not_invented(self):
        source = LETTERS.replace('Key {\n            key: Qt.Key_F\n            text: "f"\n        }', '')
        result = self.layout.add_symbol_hints(source)
        self.assertNotIn('"_f"', result)
        self.assertIn('alternativeKeys: "@aäåãâàá"', result)  # the other letters are still handled

    def test_symbol_hint_keeps_existing_corner_digit_and_appends_the_symbol(self):
        result = self.layout.add_symbol_hints(LETTERS)
        self.assertIn('alternativeKeys: "%q1"', result)   # digit kept, reachable further along
        self.assertIn('smallText: "1     %"', result)       # corner shows both, digit then symbol

    def test_symbol_hint_adds_corner_hint_where_none_existed(self):
        result = self.layout.add_symbol_hints(LETTERS)
        start, end = self.layout._find_key_block(result, 'F')
        block = result[start:end]
        self.assertIn('smallText: "_"', block)
        self.assertIn('smallTextVisible: true', block)

    def test_symbol_hint_does_not_duplicate_existing_smalltextvisible(self):
        result = self.layout.add_symbol_hints(LETTERS)
        start, end = self.layout._find_key_block(result, 'Q')
        block = result[start:end]
        self.assertEqual(block.count('smallTextVisible'), 1)

    def test_period_symbols_full_replace_in_requested_order(self):
        result = self.layout.add_period_symbols(LETTERS)
        self.assertIn(f'alternativeKeys: "{self.layout.PERIOD_SYMBOLS}"', result)
        self.assertNotIn('alternativeKeys: "!.?"', result)
        self.assertIn('smallText: "!?"', result)  # corner hint for period is untouched

    def test_period_symbols_leaves_letters_alone(self):
        result = self.layout.add_period_symbols(LETTERS)
        self.assertIn('alternativeKeys: "aäåãâàá"', result)

    def test_prepare_overrides_applies_symbol_hints_only_to_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'stock'
            (src / 'en_US').mkdir(parents=True)
            (src / 'en_US/main.qml').write_text(LETTERS)
            (src / 'fr_FR').mkdir()
            (src / 'fr_FR/main.qml').write_text(LETTERS)
            result = self.layout.prepare_overrides(src)
            self.assertIn('alternativeKeys: "@aäåãâàá"', result['en_US'])
            self.assertIn('alternativeKeys: "_f"', result['en_US'])
            self.assertIn(f'alternativeKeys: "{self.layout.PERIOD_SYMBOLS}"', result['en_US'])
            self.assertNotIn('alternativeKeys: "@aäåãâàá"', result['fr_FR'])
            self.assertNotIn('alternativeKeys: "_f"', result['fr_FR'])
            self.assertIn('alternativeKeys: "!.?"', result['fr_FR'])  # period untouched for non-English
            self.assertIn('alternativeKeys: "aäåãâàá"', result['fr_FR'])  # French keeps its own accents, untouched

    def test_failure_preserves_previous_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'stock', Path(tmp) / 'overlay'
            (src / 'fallback').mkdir(parents=True)
            (src / 'fallback/main.qml').write_text('unknown upstream format')
            (src / 'en_US').mkdir()
            dst.mkdir()
            (dst / 'precious').write_text('keep')
            with self.assertRaises(ValueError):
                self.layout.build_overlay(src, dst)
            self.assertEqual((dst / 'precious').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
