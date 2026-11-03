import pytest
from fastapi.testclient import TestClient

from marginalia import note_assets
from marginalia.api import create_app
from marginalia.jobs import JobRunner
from marginalia.note_assets import save_asset

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'


UTF16_PI = (
    "\ufeff<?xml version='1.0' encoding='UTF-16'?>\n"
    "<?xml-stylesheet type='text/css' href='https://evil.example/u.css'?>\n"
    "<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"
)


def svg(body: bytes) -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg">' + body + b"</svg>"


@pytest.fixture
def deck(course):
    course.save_manifest({"decks": [{"id": "l1", "title": "L1", "source": "materials/l1.pdf"}], "videos": []})
    (course.materials / "l1.pdf").write_bytes(b"%PDF")
    return course


def test_saves_under_deck_assets_with_content_hash(deck):
    path = save_asset(deck, "l1", "Screen Shot 2026.PNG", PNG)
    assert path.startswith("assets/screen-shot-2026-") and path.endswith(".png")
    assert (deck.dir / "notes" / "l1" / path).read_bytes() == PNG
    assert save_asset(deck, "l1", "copy.png", PNG) != path  # name follows the upload, content hash dedupes per name
    assert save_asset(deck, "l1", "Screen Shot 2026.png", PNG) == path


def test_keeps_unicode_names_and_accepts_svg(deck):
    path = save_asset(deck, "l1", "架構圖.svg", SVG)
    assert path.startswith("assets/架構圖-") and path.endswith(".svg")


def test_accepts_ordinary_drawing_tool_svgs(deck):
    inkscape = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n<!-- Created with Inkscape -->\n'
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
        b' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
        b' xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" inkscape:version="1.3">'
        b'<sodipodi:namedview id="nv" pagecolor="#fff"/>'
        b'<defs><linearGradient id="g"><stop offset="0" stop-color="#000"/></linearGradient>'
        b"<style>.a{fill:url(#g)}</style></defs>"
        b'<g inkscape:label="Layer 1"><rect class="a" width="10" height="10" style="fill:url(#g)"/>'
        + '<use xlink:href="#g"/><text x="1" y="5">作業系統</text></g></svg>'.encode()
    )
    assert save_asset(deck, "l1", "drawing.svg", inkscape).endswith(".svg")
    illustrator = (
        b"\xef\xbb\xbf<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<!-- Generator: Adobe Illustrator -->\n"
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
        b'<svg version="1.1" xmlns="http://www.w3.org/2000/svg"><text>one = 1</text><circle r="2"/></svg>'
    )
    assert save_asset(deck, "l1", "illustrator.svg", illustrator).endswith(".svg")
    assert save_asset(deck, "l1", "comment.svg", b"<!-- a -->" + SVG).endswith(".svg")


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("x.exe", PNG, "只能上傳"),
        ("x.html", b"<html>", "只能上傳"),
        ("x.png", b"GIF89a....", "不符"),
        ("x.gif", b"GIF89a....", "只能上傳"),
        ("x.webp", b"RIFF0000AVI ", "不符"),
        ("x.png", b"", "空的"),
        ("x.svg", svg(b"<script>alert(1)</script>"), "<script>"),
        ("x.svg", svg(b'<x:script xmlns:x="http://www.w3.org/2000/svg">alert(1)</x:script>'), "<script>"),
        ("x.svg", svg(b'<h:script xmlns:h="http://www.w3.org/1999/xhtml">alert(1)</h:script>'), "<script>"),
        ("x.svg", svg(b"<foreignObject><div/></foreignObject>"), "<foreignObject>"),
        ("x.svg", svg(b'<s:foreignObject xmlns:s="http://www.w3.org/2000/svg"/>'), "<foreignObject>"),
        ("x.svg", svg(b'<animate attributeName="href" values="jav&#97;script:alert(1)"/>'), "<animate>"),
        ("x.svg", svg(b'<set attributeName="onclick" to="alert(1)"/>'), "<set>"),
        ("x.svg", svg(b'<image href="https://evil.example/x.png"/>'), "<image>"),
        ("x.svg", svg(b'<a href="javascript:alert(1)"><rect/></a>'), "<a>"),
        ("x.svg", SVG.replace(b"<rect", b'<rect onload="alert(1)"'), "事件"),
        ("x.svg", SVG.replace(b"<rect", b'<rect ONclick="alert(1)"'), "事件"),
        ("x.svg", svg(b'<use href="https://evil.example/s.svg#a"/>'), "內部"),
        ("x.svg", svg(b'<use xlink:href="jav&#x61;script:x" xmlns:xlink="http://www.w3.org/1999/xlink"/>'), "內部"),
        ("x.svg", svg(b"<style>@import url(https://evil.example/a.css);</style>"), "樣式"),
        ("x.svg", svg(b"<style><![CDATA[rect{fill:url(https://evil.example/p)}]]></style>"), "樣式"),
        ("x.svg", SVG.replace(b"<rect", b'<rect style="fill:url( \'https://evil.example\' )"'), "樣式"),
        ("x.svg", SVG.replace(b"<rect", b'<rect fill="url(https://evil.example/#g)"'), "樣式"),
        ("x.svg", b"<?xml version='1.0'?><!DOCTYPE s [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><svg>&e;</svg>", "實體"),
        ("x.svg", b'<!DOCTYPE svg SYSTEM "http://evil.example/x.dtd"><svg xmlns="http://www.w3.org/2000/svg"/>', "DOCTYPE"),
        (
            "x.svg",
            (
                b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" '
                b'[<!ATTLIST svg onload CDATA "alert(1)">]><svg xmlns="http://www.w3.org/2000/svg"/>'
            ),
            "DOCTYPE",
        ),
        ("x.svg", b'<?xml version="1.0"?>\n<?xml-stylesheet type="text/css" href="https://evil.example/p.css"?>' + SVG, "處理指令"),
        ("x.svg", b'<?xml-stylesheet href="https://evil.example/p.css"?>' + SVG, "處理指令"),
        ("x.svg", SVG.replace(b"<rect", b'<?xml-stylesheet href="//evil.example/p.css"?><rect'), "處理指令"),
        ("x.svg", svg(b'<style>@\\69mport "https://evil.example/i.css";</style>'), "樣式"),
        ("x.svg", svg(b"<style>@im\\port url(https://evil.example/i.css);</style>"), "樣式"),
        ("x.svg", svg(b"<style>rect{fill:u\\72l(https://evil.example/u)}</style>"), "樣式"),
        ("x.svg", svg(b'<style>rect{background:image-set("https://evil.example/a.png" 1x)}</style>'), "樣式"),
        ("x.svg", SVG.replace(b"<rect", b'<rect style="fill:\\75rl(https://evil.example/u)"'), "樣式"),
        ("x.svg", UTF16_PI.encode("utf-16-le"), "UTF-8"),
        ("x.svg", UTF16_PI.encode("utf-16-be"), "UTF-8"),
        ("x.svg", b'<?xml version="1.0" encoding="ISO-8859-1"?>' + SVG, "UTF-8"),
        ("x.svg", b"<svg><rect/></svg>", "格式"),
        ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><rect></svg>", "格式"),
        ("x.svg", b"<html><svg/></html>", "格式"),
    ],
)
def test_rejects_bad_files(deck, name, data, message):
    with pytest.raises(ValueError, match=message):
        save_asset(deck, "l1", name, data)


def test_rejects_oversized(deck, monkeypatch):
    monkeypatch.setattr(note_assets, "MAX_BYTES", 16)
    with pytest.raises(ValueError, match="10 MB"):
        save_asset(deck, "l1", "x.png", PNG)


@pytest.mark.parametrize("name", ["../../evil.png", "..\\..\\evil.png", "/etc/evil.png", "a/../../b.png"])
def test_filenames_cannot_escape(deck, name):
    path = save_asset(deck, "l1", name, PNG)
    assert "/" not in path.removeprefix("assets/") and ".." not in path
    assert (deck.dir / "notes" / "l1" / path).is_file()


@pytest.mark.parametrize("deck_id", ["missing", "../l1", ".hidden", "l1/../x"])
def test_unknown_or_bad_deck(deck, deck_id):
    with pytest.raises(LookupError):
        save_asset(deck, deck_id, "x.png", PNG)


def test_http_endpoint(deck):
    client = TestClient(create_app(JobRunner()))
    url = "/api/courses/fixture/decks/l1/assets"
    response = client.post(url, files={"file": ("pic.png", PNG, "image/png")})
    assert response.status_code == 200 and response.json()["path"].startswith("assets/pic-")
    assert client.post(url, files={"file": ("pic.txt", b"hi", "text/plain")}).status_code == 422
    assert client.post("/api/courses/fixture/decks/nope/assets", files={"file": ("p.png", PNG)}).status_code == 404
    assert client.post("/api/courses/nope/decks/l1/assets", files={"file": ("p.png", PNG)}).status_code == 404
    assert client.post("/api/courses/..%2F..%2Fetc/decks/l1/assets", files={"file": ("p.png", PNG)}).status_code == 404


def test_http_rejects_oversized_body_before_parsing(deck):
    client = TestClient(create_app(JobRunner()))
    url = "/api/courses/fixture/decks/l1/assets"
    big = PNG + b"\0" * (note_assets.MAX_BYTES + 128 * 1024)
    assert client.post(url, files={"file": ("big.png", big, "image/png")}).status_code == 413
    assert client.post(url, content=b"x", headers={"content-length": "nope"}).status_code == 411


def test_served_svg_cannot_load_anything(deck):
    client = TestClient(create_app(JobRunner()))
    path = client.post("/api/courses/fixture/decks/l1/assets", files={"file": ("d.svg", SVG, "image/svg+xml")}).json()["path"]
    response = client.get(f"/files/fixture/notes/l1/{path}")
    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("default-src 'none'")

