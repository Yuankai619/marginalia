"""Remove video citations from model-written untaught notes without a Markdown dependency.

Handle common Markdown/HTML links; a separate, conservative scheme check catches anything left over,
including escaped or entity-encoded destinations, so unfamiliar syntax cannot pass review silently.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

ESCAPE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])")
SCHEME = re.compile(r"video:", re.IGNORECASE)
INLINE = re.compile(r"\[(?:[^\[\]\n]|\[[^\]\n]*\])*\]\(\s*([^\n)]*)\)")
DEFINITION = re.compile(r"^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(?:\n[ \t]*)?([^\n]+)", re.MULTILINE)
REFERENCE = re.compile(r"\[([^\]\n]+)\](?:[ \t]*(?:\n[ \t]*)?\[([^\]\n]*)\])?")
AUTOLINK = re.compile(r"<([^<>\s]+)>")
ANCHOR = re.compile(r"<a\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>(?:.*?</a\s*>)?", re.IGNORECASE | re.DOTALL)


def decoded(text: str) -> str:
    return html.unescape(ESCAPE.sub(r"\1", text))


def has_video_links(body: str) -> bool:
    """Conservative postcondition, independent of link syntax (also flags schemes in code/examples)."""
    return bool(SCHEME.search(decoded(body)))


def _destination(text: str) -> bool:
    return bool(SCHEME.match(decoded(text).lstrip("< \t")))


def _label(text: str) -> str:
    return " ".join(decoded(text).split()).casefold()


class _Anchor(HTMLParser):
    video = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.video |= tag == "a" and any(k == "href" and _destination(v or "") for k, v in attrs)


def strip_video_links(body: str) -> str:
    refs: set[str] = set()

    def definition(m: re.Match) -> str:
        if not _destination(m[2]):
            return m[0]
        refs.add(_label(m[1]))
        return ""

    def anchor(m: re.Match) -> str:
        parser = _Anchor()
        parser.feed(m[0])
        return "" if parser.video else m[0]

    body = ANCHOR.sub(anchor, body)
    body = INLINE.sub(lambda m: "" if _destination(m[1]) else m[0], body)
    body = DEFINITION.sub(definition, body)
    body = REFERENCE.sub(lambda m: "" if _label(m[2] or m[1]) in refs else m[0], body)
    return AUTOLINK.sub(lambda m: "" if _destination(m[1]) else m[0], body).strip()
