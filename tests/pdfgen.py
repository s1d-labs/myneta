"""A tiny PDF writer for test fixtures: pages of text lines and ruled tables (Helvetica, no dependencies).

Real Form 24A, electoral trust and audit PDFs are on eci.gov.in, which refuses the team's IP from members' boxes, so their
parsers are tested on synthetic documents laid out like the real ones; the bond parser is tested on real pages."""


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def _text(x, y, s, size=8):
    return f"BT /F1 {size} Tf {x:.1f} {y:.1f} Td ({_esc(s)}) Tj ET\n"


def table(ops, x, y, widths, rows, line_h=11, pad=3):
    """Draw a ruled table with its top-left corner at (x, y); cells may hold several lines ('\\n'). Returns the bottom y."""
    for row in rows:
        lines = max(len(str(c).split("\n")) for c in row)
        h = lines * line_h + 2 * pad
        cx = x
        for w, cell in zip(widths, row):
            ops.append(f"{cx:.1f} {y - h:.1f} {w:.1f} {h:.1f} re S\n")
            for i, part in enumerate(str(cell).split("\n")):
                ops.append(_text(cx + pad, y - pad - (i + 1) * line_h + 2, part))
            cx += w
        y -= h
    return y


def page(lines=(), tables=(), rects_only=False):
    """One page's content stream: text lines from the top, then tables [(widths, rows)] below them."""
    ops, y = [], 800
    for s in lines:
        ops.append(_text(40, y, s, 10))
        y -= 14
    for widths, rows in tables:
        y = table(ops, 40, y - 10, widths, rows) - 10
    if rects_only:                                    # a 'scan': an image-like box and no text layer at all
        ops = ["40 40 515 760 re S\n", "60 60 475 720 re f\n"]
    return "".join(ops)


def pdf(pages):
    """bytes of a PDF with the given page content streams (A4)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for content in pages:
        data = content.encode("latin-1")
        objs.append(f"<< /Length {len(data)} >>\nstream\n{content}endstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
