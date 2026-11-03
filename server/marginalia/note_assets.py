"""Images pasted or dropped into the note editor, stored next to the notes as `notes/<deck>/assets/<name>`.

Notes reference them as `![說明](assets/<name>)` (see docs/architecture.md, Note format). Files are named after
the upload plus a content hash, so pasting the same screenshot twice keeps one copy. The browser renders them only through
`<img>` and `/files` serves SVG as a download, but a static export may serve them inline, so SVGs must be plain
drawings: parsed with ElementTree (no DTDs), allowlisted elements, no event handlers, no references outside the file.
"""

from __future__ import annotations

import hashlib
import re
from xml.etree import ElementTree

from . import config
from .store import Course, exclusive_output, slugify, validate_id

MAX_BYTES = 10 * 1024 * 1024
TYPES = {  # extension -> leading bytes that identify the format
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),
    "svg": (),
}

class AssetError(ValueError):
    """A problem with the uploaded file itself; the message is safe to show the user."""


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
# Editor metadata Inkscape and friends leave in exports; browsers never render these namespaces.
METADATA_NS = {
    "http://www.inkscape.org/namespaces/inkscape",
    "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://creativecommons.org/ns#",
    "http://purl.org/dc/elements/1.1/",
}
# Static drawing only: no script, foreignObject, animation, embedded images or links.
SVG_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "title", "desc", "metadata", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask", "marker",
    "filter", "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite", "feDropShadow",
    "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR", "feGaussianBlur", "feMerge",
    "feMergeNode", "feMorphology", "feOffset",
}
_URL = re.compile(r"url\s*\(\s*['\"]?\s*([^)'\"\s]*)", re.IGNORECASE)


def _split(name: str) -> tuple[str, str]:
    if name.startswith("{"):
        namespace, _, local = name[1:].partition("}")
        return namespace, local
    return "", name


_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|\r\n|\n|(.))", re.DOTALL)
# Ways CSS can load something other than url(): at-rules and image functions that take plain strings.
_CSS_LOADERS = ("@import", "expression(", "javascript:", "image-set(", "image(", "src(", "cross-fade(", "element(")


def _css_unescape(text: str) -> str:
    """Resolve CSS escapes (`@\\69mport` is `@import`) so checks see what the browser will see."""

    def char(match: re.Match[str]) -> str:
        if match.group(1):
            code = int(match.group(1), 16)
            return chr(code) if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else "\ufffd"
        return match.group(2) or ""

    return _CSS_ESCAPE.sub(char, text)


def _safe_css(text: str) -> bool:
    plain = _css_unescape(text)
    squashed = re.sub(r"[\s\x00-\x1f]+", "", plain).lower()
    if any(loader in squashed for loader in _CSS_LOADERS):
        return False
    return all(target.startswith("#") for target in _URL.findall(plain))


# The only DOCTYPEs drawing tools write; anything else (internal subsets, entities, other DTDs) is refused
# before parsing, which rules out entity expansion and external fetches.
_STANDARD_DOCTYPE = re.compile(
    rb'<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1\.[01]( Basic| Tiny)?//EN"\s+'
    rb'"http://www\.w3\.org/(Graphics/SVG/1\.1/DTD/svg11|TR/2001/REC-SVG-20010904/DTD/svg10)(-basic|-tiny)?\.dtd"\s*>'
)


def _check_svg(data: bytes) -> None:
    data = data.removeprefix(b"\xef\xbb\xbf")
    # Every byte-level check below assumes UTF-8; a UTF-16 file would hide `<?…?>` from them.
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssetError("SVG 必須是 UTF-8 編碼") from exc
    encoding = re.match(rb"""\s*<\?xml\s[^?]*encoding\s*=\s*["']([^"']+)["']""", data)
    if encoding and encoding.group(1).lower() not in {b"utf-8", b"utf8"}:
        raise AssetError("SVG 必須是 UTF-8 編碼")
    # ElementTree drops processing instructions, so `<?xml-stylesheet href=…?>` would pass the tree checks and
    # stay in the saved bytes. Only the XML declaration itself is allowed.
    declaration = re.match(rb"\s*<\?xml\s[^?]*\?>", data)
    if b"<?" in data[declaration.end() if declaration else 0 :]:
        raise AssetError("SVG 不能包含 <?…?> 處理指令（例如外部樣式表）")
    if re.search(rb"<!\s*entity", data, re.IGNORECASE):
        raise AssetError("SVG 不能包含實體宣告")
    if re.search(rb"<!\s*doctype", _STANDARD_DOCTYPE.sub(b"", data, count=1), re.IGNORECASE):
        raise AssetError("SVG 不能包含自訂的 DOCTYPE")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise AssetError("SVG 格式不正確") from exc
    if _split(root.tag) != (SVG_NS, "svg"):
        raise AssetError("SVG 格式不正確")
    for element in root.iter():
        namespace, local = _split(element.tag) if isinstance(element.tag, str) else ("", "")
        if namespace in METADATA_NS:
            continue
        if namespace != SVG_NS or local not in SVG_ELEMENTS:
            raise AssetError(f"SVG 不能包含 <{local or '?'}> 元素")
        if local == "style" and not _safe_css(element.text or ""):
            raise AssetError("SVG 樣式不能引用外部資源")
        for name, value in element.attrib.items():
            attr_ns, attr = _split(name)
            if attr_ns in METADATA_NS:
                continue
            if attr.lower().startswith("on"):
                raise AssetError("SVG 不能包含事件屬性")
            if attr == "href" and attr_ns in {"", XLINK_NS} and not value.strip().startswith("#"):
                raise AssetError("SVG 只能引用檔案內部的元素")
            if not _safe_css(value):
                raise AssetError("SVG 樣式不能引用外部資源")


def _extension(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ext = {"jpeg": "jpg"}.get(ext, ext)
    if ext not in TYPES:
        raise AssetError("只能上傳 png、jpg、webp 或 svg 圖片")
    return ext


def _check_content(ext: str, data: bytes) -> None:
    if not data:
        raise AssetError("圖片是空的")
    if ext == "svg":
        _check_svg(data)
        return
    if not any(data.startswith(magic) for magic in TYPES[ext]) or (ext == "webp" and data[8:12] != b"WEBP"):
        raise AssetError("檔案內容和副檔名不符")


def save_asset(course: Course, deck: str, filename: str, data: bytes) -> str:
    """Store one image for `deck` and return the path notes use (`assets/<name>`)."""
    try:
        known = course.deck(validate_id(deck))
    except ValueError:
        known = None
    if known is None:
        raise LookupError("找不到投影片")
    if len(data) > MAX_BYTES:
        raise AssetError("圖片不能超過 10 MB")
    ext = _extension(filename)
    _check_content(ext, data)
    stem = slugify(filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])[:40].strip("-_") or "image"
    name = f"{stem}-{hashlib.sha256(data).hexdigest()[:10]}.{ext}"
    try:
        with exclusive_output(course.path(config.NOTES, deck, "assets", name), root=course.notes_dir) as output:
            output.write(data)
    except FileExistsError:
        pass  # same name and content hash: this image is already there
    return f"assets/{name}"

