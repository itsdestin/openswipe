# SPDX-FileCopyrightText: 2026 Destin Moss <https://youcoded.ai>
#
# SPDX-License-Identifier: MIT

"""Private language hooks over each stock physical layout, without activating a profile."""
from pathlib import Path
import re
import shutil
import tempfile

HOOK = '''
    // WHY hook, not layout replacement: Qt retains this locale and its physical keys. The plugin
    // verifies the selected profile and its assets; unavailable swiping keeps tapping.
    sharedLayouts: ['symbols']
    function createInputMethod() {
        try {
            return Qt.createQmlObject('import QtQuick; import SwipeKeyboard; SwipeInputMethod {}', parent, "swipe-keyboard")
        } catch (e) {
            console.warn("OpenSwipe unavailable; using normal tapping:", e)
            return null
        }
    }
    property Item swipeCapture: null
    Component.onCompleted: {
        var c = Qt.createComponent("SwipeKeyboard", "SwipeCapture")
        if (c.status === Component.Ready)
            swipeCapture = c.createObject(keyboard.keyboardInputArea,
                { layoutItem: swipeLayout, touchArea: keyboard.keyboardInputArea })
    }
    Component.onDestruction: if (swipeCapture) swipeCapture.destroy()
'''


def patch_layout(source):
    """Preserve upstream bytes/keys; accept only an uncustomised Latin KeyboardLayout root."""
    # WHY strip only for inspection, preserving offsets: braces/keywords in quoted keys and comments
    # are not QML structure. Never rewrite the physical source while validating the hook location.
    tokens = r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    code = re.sub(tokens, lambda m: re.sub(r'[^\n]', ' ', m[0]), source, flags=re.S)
    match = re.search(r'\bKeyboardLayout\s*\{', code)
    prefix = re.sub(r'(?m)^\s*import\s+[\w.]+(?:\s+\d+\.\d+)?(?:\s+as\s+\w+)?\s*;?\s*$', '',
                    code[:match.start()] if match else code)
    if not match or prefix.strip() or any(c in code for c in ('"', "'", '`')):
        raise ValueError('Unrecognised Plasma Keyboard Latin layout; stock keyboard is unchanged.')
    depth, end, root = 1, None, []
    for index in range(match.end(), len(code)):
        char = code[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        elif depth == 1:
            root.append(char)
        if depth == 0:
            end = index
            break
    properties = ''.join(root)
    if (end is None or code[end + 1:].strip() or not re.search(r'\bSpaceKey\s*\{', code) or
            not re.search(r'\binputMode\s*:\s*InputEngine\.InputMode\.Latin\b', properties)):
        raise ValueError('Unrecognised Plasma Keyboard Latin layout; stock keyboard is unchanged.')
    if (re.search(r'\b(?:id|inputMethod)\s*:', properties) or re.search(r'\bid\s*:\s*swipeLayout\b', code) or
            any(token in code for token in ('createInputMethod', 'sharedLayouts', 'Component.onCompleted', 'Component.onDestruction'))):
        raise ValueError('Latin layout already has custom integration; refusing to replace it.')
    return source[:match.end()] + '\n    id: swipeLayout' + source[match.end():end] + HOOK + source[end:]


def patch_english(source):
    """Compatibility entry point; eligibility no longer implies an English locale."""
    return patch_layout(source)


# Gboard's standard English QWERTY long-press scheme, by key (card request 2026-11-09). Values are
# the literal text a QML double-quoted string needs to contain for that symbol, not always the
# symbol's own character: backslash and the double quote are themselves QML string escapes, so W's
# value is the two-character escaped-backslash form (\\) and X's is the escaped-quote form (\").
GBOARD_SYMBOL_HINTS = {
    'Q': '%', 'W': '\\\\', 'E': '|', 'R': '=', 'T': '[', 'Y': ']', 'U': '<', 'I': '>', 'O': '{', 'P': '}',
    'A': '@', 'S': '#', 'D': '$', 'F': '_', 'G': '&', 'H': '-', 'J': '+', 'K': '(', 'L': ')',
    'Z': '*', 'X': '\\"', 'C': ':', 'V': ';', 'B': "'", 'N': '!', 'M': '?',
}
# Trimmed from the originally requested 16 (card 2026-11-09): Qt Virtual Keyboard's long-press
# popup is a single-row horizontal strip with no wrap/grid mode, and the full 16-symbol list ran
# off both edges of the screen on this device. Dropped: "," (already its own dedicated key next to
# period), "% + & #" (more math/programming-leaning), and "@" (an 11-item row still clipped its
# first entry against the screen edge). The period's own character is deliberately not in the list
# (a plain tap still types it regardless of this list; only a stationary long-press-release, an
# existing Qt quirk on every key, would land on the list's first entry instead).
PERIOD_SYMBOLS = '\\"-:\';/()!?'


def _find_key_block(source, letter, start_at=0):
    """Byte range (start, end) of the next Key { ... } block for Qt.Key_<letter>, or None.
    Brace counting skips quoted-string contents: O and P's own Gboard symbols are "{" and "}", and
    a value like alternativeKeys: "{..." must never be mistaken for real QML structure."""
    pos = start_at
    while True:
        match = re.search(r'\bKey\s*\{', source[pos:])
        if not match:
            return None
        start = pos + match.start()
        depth, end, in_string, escape = 1, None, False, False
        index = pos + match.end()
        while index < len(source):
            char = source[index]
            if in_string:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
            index += 1
        if end is None:
            return None
        if re.search(rf'\bkey\s*:\s*Qt\.Key_{letter}\b', source[start:end]):
            return start, end
        pos = end


def _line_indent(block, pos):
    """Leading whitespace of the line containing offset pos, or a plain 4-space fallback when
    other content shares that line (e.g. a semicolon-separated one-line Key block)."""
    line_start = block.rfind('\n', 0, pos) + 1
    candidate = block[line_start:pos]
    return candidate if candidate.strip() == '' else '    '


def add_symbol_hints(source, hints=GBOARD_SYMBOL_HINTS):
    """Give every target letter a Gboard-style symbol (card request 2026-11-09): prepended as the
    first long-press option ahead of its existing accents/digits, and shown in the key's permanent
    top-right hint — for q-p, appended after the digit already shown there (same corner, same
    append-don't-replace trick the stock period key already uses for "!?"), so both stay visible
    without needing a second hint property Qt's Key component has no slot for. English layouts only
    — the scheme is a QWERTY hand-position convention, not meaningful on AZERTY/QWERTZ physical
    layouts. Silently leaves a letter untouched if its Key block cannot be found (never invents
    one), matching this module's existing fail-closed-but-never-guess style."""
    for letter, symbol in hints.items():
        found = _find_key_block(source, letter)
        if not found:
            continue
        start, end = found
        block = source[start:end]

        existing_alt = re.search(r'alternativeKeys\s*:\s*"((?:\\.|[^"\\])*)"', block)
        if existing_alt:
            block = block[:existing_alt.start(1)] + symbol + block[existing_alt.start(1):]
            alt_end = existing_alt.end() + len(symbol)
        else:
            text_match = re.search(r'text\s*:\s*"(?:\\.|[^"\\])*"', block)
            if not text_match:
                continue
            indent = _line_indent(block, text_match.start())
            insertion = f'\n{indent}alternativeKeys: "{symbol}{letter.lower()}"'
            block = block[:text_match.end()] + insertion + block[text_match.end():]
            alt_end = text_match.end() + len(insertion)

        existing_small = re.search(r'smallText\s*:\s*"((?:\\.|[^"\\])*)"', block)
        if existing_small:
            # WHY append with a gap, not replace (card 2026-11-09): q-p's existing digit stays
            # visible too, in the same corner slot, the same way the period key already shows "!?"
            # together — avoids needing a second hint property/corner, which Qt's Key component has
            # no slot for. The style's Label is right-anchored as one block (style.qml, Breeze), so
            # padding before the symbol pushes the digit visually toward the key's left while the
            # symbol stays pinned at the actual top-right corner — a cheap stand-in for two corners.
            block = block[:existing_small.end(1)] + '     ' + symbol + block[existing_small.end(1):]
        else:
            indent = _line_indent(block, alt_end)
            block = block[:alt_end] + f'\n{indent}smallText: "{symbol}"' + block[alt_end:]
        if 'smallTextVisible' not in block:
            small_match = re.search(r'smallText\s*:\s*"(?:\\.|[^"\\])*"', block)
            indent = _line_indent(block, small_match.start())
            block = (block[:small_match.end()] + f'\n{indent}smallTextVisible: true' +
                    block[small_match.end():])

        source = source[:start] + block + source[end:]
    return source


def add_period_symbols(source, symbols=PERIOD_SYMBOLS):
    """Replace the period key's "!.?" long-press list with the full requested set (card
    2026-11-09). A full replace, not a prepend: the caller specified the exact complete list and
    order they want, unlike the per-letter hints above which keep each locale's existing accents."""
    found = _find_key_block(source, 'Period')
    if not found:
        return source
    start, end = found
    block = source[start:end]
    existing = re.search(r'alternativeKeys\s*:\s*"((?:\\.|[^"\\])*)"', block)
    if not existing:
        return source
    block = block[:existing.start(1)] + symbols + block[existing.end(1):]
    return source[:start] + block + source[end:]


def prepare_overrides(stock):
    """Read-only preflight shared by setup and staging; no fabricated absent locale directories."""
    stock = Path(stock)
    if not (stock / 'en_US').is_dir():
        raise ValueError('Stock Plasma Keyboard English layouts are missing.')
    targets = re.compile(r'(?:en_(?:US|GB)|(?:es|fr|de)(?:_[A-Za-z]{4})?(?:_(?:[A-Z]{2}|[0-9]{3}))?)')
    overrides = {}
    for folder in sorted(stock.iterdir()):
        if not folder.is_dir() or not targets.fullmatch(folder.name):
            continue
        main = folder / 'main.qml'
        if not main.is_file():
            marker = folder / 'main.fallback'
            # WHY empty only: this is Qt's default-fallback presence marker, NOT another locale's name.
            # Resolve it exactly as stock does; never substitute en_US or a same-language sibling.
            if not marker.is_file() or marker.read_text().strip():
                raise ValueError(f'Unsupported {folder.name} fallback; refusing to guess which layout to change.')
            main = stock / 'fallback/main.qml'
        try:
            patched = patch_layout(main.read_text())
            if folder.name.startswith('en'):
                patched = add_symbol_hints(patched)
                patched = add_period_symbols(patched)
            overrides[folder.name] = patched
        except (OSError, ValueError) as error:
            raise ValueError(f'{folder.name}: {error}') from error
    return overrides


def build_overlay(stock, destination):
    """Stage completely before replacing our private copy; never modify upstream/user layouts."""
    stock, destination = Path(stock), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.layouts-', dir=destination.parent) as temp:
        staged = Path(temp) / 'layouts'
        shutil.copytree(stock, staged)
        # WHY validate the staged copy: no target is published if any locale has unsupported/custom drift,
        # and a concurrent stock update cannot mismatch the source we validate and the bytes we publish.
        for locale, patched in prepare_overrides(staged).items():
            (staged / locale / 'main.fallback').unlink(missing_ok=True)
            (staged / locale / 'main.qml').write_text(patched)
        # WHY rename with rollback: a failed rebuild must not destroy the last usable layout tree.
        previous = destination.with_name(destination.name + '.previous')
        if previous.exists():
            raise ValueError('An interrupted layout replacement needs inspection: ' + str(previous))
        if destination.exists():
            destination.rename(previous)
        try:
            staged.rename(destination)
        except OSError:
            if previous.exists():
                previous.rename(destination)
            raise
        if previous.exists():
            shutil.rmtree(previous)
