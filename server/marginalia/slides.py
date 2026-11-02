"""Turn a deck (pptx/pdf/…) into slide images plus per-slide text."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from . import config
from .store import Course, slide_name, write_json


def _to_pdf(src: Path, out_dir: Path) -> Path:
    if src.suffix.lower() == ".pdf":
        dst = out_dir / "deck.pdf"
        shutil.copyfile(src, dst)
        return dst
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("需要 LibreOffice（soffice）才能把簡報轉成 PDF")
    with tempfile.TemporaryDirectory() as tmp:
        # private profile so this never collides with a LibreOffice the user has open
        profile = Path(tmp) / "profile"
        subprocess.run(
            [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
            check=True, capture_output=True, timeout=600,
        )
        pdfs = list(Path(tmp).glob("*.pdf"))
        if not pdfs:
            raise RuntimeError(f"LibreOffice 沒有產出 PDF：{src.name}")
        dst = out_dir / "deck.pdf"
        shutil.move(pdfs[0], dst)
        return dst


def _pdf_pages(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return 0


def _pdf_text(pdf: Path, page: int) -> str:
    r = subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf), "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def _shape_texts(shapes) -> list[str]:
    out = []
    for sh in shapes:
        if sh.shape_type == 6:  # group
            out += _shape_texts(sh.shapes)
        elif getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
            out.append(sh.text_frame.text.replace("\x0b", "\n").strip())
        elif getattr(sh, "has_table", False):
            rows = [" | ".join(c.text.strip() for c in r.cells) for r in sh.table.rows]
            out.append("\n".join(rows))
    return out


def _pptx_slides(src: Path) -> list[dict] | None:
    try:
        from pptx import Presentation
    except ImportError:
        return None
    prs = Presentation(str(src))
    out = []
    for s in prs.slides:
        if s._element.get("show") == "0":
            continue  # LibreOffice leaves hidden slides out of the PDF
        title = ""
        if s.shapes.title is not None and s.shapes.title.has_text_frame:
            title = s.shapes.title.text_frame.text.replace("\x0b", " ").strip()
        texts = _shape_texts(s.shapes)
        notes = ""
        if s.has_notes_slide and s.notes_slide.notes_text_frame is not None:
            notes = s.notes_slide.notes_text_frame.text.strip()
        out.append({"title": title, "text": "\n".join(texts), "speakerNotes": notes})
    return out


def render_deck(course: Course, deck_id: str, progress=lambda f, m: None) -> list[dict]:
    deck = course.deck(deck_id)
    if not deck:
        raise KeyError(deck_id)
    src = course.source_path(deck["source"])
    ddir = course.deck_dir(deck_id)
    course.deck_path(deck_id, "deck.pdf")
    course.deck_path(deck_id, "slides").mkdir(parents=True, exist_ok=True)
    course.deck_path(deck_id, "thumbs").mkdir(parents=True, exist_ok=True)

    progress(0.05, "轉成 PDF")
    pdf = _to_pdf(src, ddir)
    n = _pdf_pages(pdf)

    progress(0.3, f"產生 {n} 張投影片圖片")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-png", "-scale-to-x", str(config.SLIDE_WIDTH), "-scale-to-y", "-1", str(pdf), f"{tmp}/p"],
            check=True,
        )
        pngs = sorted(Path(tmp).glob("p-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        for i, png in enumerate(pngs, 1):
            im = Image.open(png).convert("RGB")
            im.save(course.deck_path(deck_id, "slides", f"{slide_name(i)}.webp"), quality=88)
            th = im.copy()
            th.thumbnail((config.THUMB_WIDTH, config.THUMB_WIDTH))
            th.save(course.deck_path(deck_id, "thumbs", f"{slide_name(i)}.webp"), quality=80)
            progress(0.3 + 0.6 * i / max(n, 1), f"投影片 {i}/{n}")

    meta = _pptx_slides(src) if src.suffix.lower() == ".pptx" else None
    if meta is not None and len(meta) != n:
        meta = None  # page count drifted (e.g. animations exported as pages); trust the PDF
    slides = []
    with Image.open(course.deck_path(deck_id, "slides", f"{slide_name(1)}.webp")) as first:
        w, h = first.size
    for i in range(1, n + 1):
        m = meta[i - 1] if meta else {}
        text = m.get("text") or _pdf_text(pdf, i)
        title = m.get("title") or next((ln.strip() for ln in text.splitlines() if ln.strip()), f"Slide {i}")
        slides.append({"index": i, "title": title, "text": text, "speakerNotes": m.get("speakerNotes", "")})
    write_json(course.deck_path(deck_id, "slides.json"), slides)

    man = course.manifest()
    for d in man["decks"]:
        if d["id"] == deck_id:
            d.update(slideCount=n, width=w, height=h, rendered=True)
    course.save_manifest(man)
    progress(1.0, f"完成：{n} 張")
    return slides
