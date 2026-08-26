"""Render the architecture guide HTML into a portable PDF using ReportLab."""

from html import escape
from html.parser import HTMLParser
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, KeepTogether,
)


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "architecture-and-feature-removal-guide.html"
OUTPUT = ROOT / "architecture-and-feature-removal-guide.pdf"


class Node:
    def __init__(self, tag="root", attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
        self.children = []

    def text(self):
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)


class TreeParser(HTMLParser):
    VOID = {"meta", "link", "br", "hr", "img", "input"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        cursor = self.current
        while cursor.parent is not None:
            if cursor.tag == tag:
                self.current = cursor.parent
                return
            cursor = cursor.parent

    def handle_data(self, data):
        self.current.children.append(data)


def inline(node):
    if isinstance(node, str):
        return escape(node)
    content = "".join(inline(child) for child in node.children)
    if node.tag in {"b", "strong"}:
        return f"<b>{content}</b>"
    if node.tag in {"i", "em"}:
        return f"<i>{content}</i>"
    if node.tag == "code":
        return f'<font name="DejaVuMono" color="#184f8c">{content}</font>'
    if node.tag == "br":
        return "<br/>"
    return content


def clean_markup(node):
    return " ".join(inline(node).split())


def register_fonts():
    candidates = [
        ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("DejaVu", regular))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
            break
    mono = "C:/Windows/Fonts/consola.ttf"
    pdfmetrics.registerFont(TTFont("DejaVuMono", mono if Path(mono).exists() else regular))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")


def styles():
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="DejaVu", fontSize=9.2, leading=13.2, textColor=colors.HexColor("#172033"), spaceAfter=6),
        "h1": ParagraphStyle("H1", fontName="DejaVu-Bold", fontSize=27, leading=32, textColor=colors.HexColor("#12213f"), alignment=TA_CENTER, spaceAfter=18),
        "h2": ParagraphStyle("H2", fontName="DejaVu-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#163a70"), spaceBefore=12, spaceAfter=8),
        "h3": ParagraphStyle("H3", fontName="DejaVu-Bold", fontSize=11.5, leading=15, textColor=colors.HexColor("#205493"), spaceBefore=8, spaceAfter=4),
        "small": ParagraphStyle("Small", fontName="DejaVu", fontSize=7.8, leading=10.5, textColor=colors.HexColor("#64748b")),
        "bullet": ParagraphStyle("Bullet", fontName="DejaVu", fontSize=9, leading=12.6, leftIndent=14, firstLineIndent=-8, bulletIndent=4, spaceAfter=3),
        "flow": ParagraphStyle("Flow", fontName="DejaVuMono", fontSize=7.8, leading=11.5, textColor=colors.HexColor("#e2e8f0"), backColor=colors.HexColor("#0f172a"), borderPadding=10, spaceAfter=8),
        "callout": ParagraphStyle("Callout", fontName="DejaVu", fontSize=8.8, leading=12.5, backColor=colors.HexColor("#eff6ff"), borderColor=colors.HexColor("#2563eb"), borderWidth=0.8, borderPadding=8, spaceAfter=8),
        "cover_sub": ParagraphStyle("CoverSub", fontName="DejaVu", fontSize=13, leading=19, textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=20),
        "cover_meta": ParagraphStyle("CoverMeta", fontName="DejaVu", fontSize=9, leading=14, textColor=colors.HexColor("#64748b"), alignment=TA_CENTER),
    }


def find(node, tag):
    if node.tag == tag:
        return node
    for child in node.children:
        if not isinstance(child, str):
            found = find(child, tag)
            if found:
                return found
    return None


def make_table(node, st):
    rows = []
    for child in node.children:
        if isinstance(child, str):
            continue
        candidates = child.children if child.tag in {"thead", "tbody"} else [child]
        for row in candidates:
            if isinstance(row, str) or row.tag != "tr":
                continue
            cells = [c for c in row.children if not isinstance(c, str) and c.tag in {"th", "td"}]
            if cells:
                rows.append([Paragraph(clean_markup(c), st["small"]) for c in cells])
    if not rows:
        return None
    widths = [175 * mm / len(rows[0])] * len(rows[0])
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163a70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_story(body, st):
    story = []
    sections = [c for c in body.children if not isinstance(c, str) and c.tag == "section"]
    for index, section in enumerate(sections):
        if index:
            story.append(PageBreak())
        is_cover = "cover" in section.attrs.get("class", "")
        if is_cover:
            story.extend([Spacer(1, 42 * mm)])
        list_counter = 0
        for node in section.children:
            if isinstance(node, str):
                continue
            cls = node.attrs.get("class", "")
            if node.tag == "h1": story.append(Paragraph(clean_markup(node), st["h1"]))
            elif node.tag == "h2": story.append(Paragraph(clean_markup(node), st["h2"]))
            elif node.tag == "h3": story.append(Paragraph(clean_markup(node), st["h3"]))
            elif node.tag == "p":
                style = st["cover_sub"] if is_cover and "subtitle" in cls else st["cover_meta"] if is_cover and "meta" in cls else st["small"] if "small" in cls else st["body"]
                story.append(Paragraph(clean_markup(node), style))
            elif node.tag == "div":
                style = st["flow"] if "flow" in cls else st["callout"]
                story.append(Paragraph(clean_markup(node).replace(" → ", " →<br/> "), style))
            elif node.tag in {"ul", "ol"}:
                list_counter = 0
                for item in [x for x in node.children if not isinstance(x, str) and x.tag == "li"]:
                    list_counter += 1
                    marker = f"{list_counter}." if node.tag == "ol" else "•"
                    story.append(Paragraph(f"{marker} {clean_markup(item)}", st["bullet"]))
            elif node.tag == "table":
                table = make_table(node, st)
                if table:
                    story.extend([table, Spacer(1, 7)])
        if is_cover:
            story.append(Spacer(1, 20 * mm))
    return story


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("DejaVu", 7.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(15 * mm, 9 * mm, "Chat With Unknown Data — Architecture & Feature Removal Guide")
    canvas.drawRightString(195 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    register_fonts()
    parser = TreeParser()
    parser.feed(SOURCE.read_text(encoding="utf-8"))
    body = find(parser.root, "body")
    st = styles()
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=15 * mm, bottomMargin=16 * mm, title="Architecture and Feature Removal Guide", author="OpenAI Codex")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(PageTemplate(id="guide", frames=[frame], onPage=footer))
    doc.build(build_story(body, st))
    print(OUTPUT)


if __name__ == "__main__":
    main()
