"""Render the RAG and downstream layers HTML guide as a portable PDF."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

from render_architecture_pdf import TreeParser, build_story, find, register_fonts, styles


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "rag-and-downstream-layers-guide.html"
OUTPUT = ROOT / "rag-and-downstream-layers-guide.pdf"
TITLE = "RAG and Downstream Layers Guide"


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("DejaVu", 7.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(15 * mm, 9 * mm, TITLE)
    canvas.drawRightString(195 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    register_fonts()
    parser = TreeParser()
    parser.feed(SOURCE.read_text(encoding="utf-8"))
    body = find(parser.root, "body")
    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=17 * mm, rightMargin=17 * mm,
        topMargin=15 * mm, bottomMargin=16 * mm,
        title=TITLE, author="OpenAI Codex",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(PageTemplate(id="guide", frames=[frame], onPage=footer))
    doc.build(build_story(body, styles()))
    print(OUTPUT)


if __name__ == "__main__":
    main()
