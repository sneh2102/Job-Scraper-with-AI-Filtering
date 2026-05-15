import os
import shutil
import subprocess
import logging
import tempfile
from reportlab.lib.units import inch, cm

logger = logging.getLogger(__name__)

PDFLATEX_PATH = r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe"


def is_pdflatex_available() -> bool:
    if shutil.which("pdflatex"):
        return True
    if os.path.isfile(PDFLATEX_PATH):
        return True
    try:
        result = subprocess.run(
            ["pdflatex", "--version"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def compile_latex_to_pdf(latex_code: str, output_pdf_path: str) -> bool:
    """Compiles LaTeX source to PDF using pdflatex. Returns True on success."""

    pdflatex_cmd = shutil.which("pdflatex")
    if not pdflatex_cmd:
        if os.path.isfile(PDFLATEX_PATH):
            pdflatex_cmd = PDFLATEX_PATH
        else:
            logger.error("pdflatex not found.")
            _save_latex_fallback(latex_code, output_pdf_path)
            return False
    safe_tmp = "C:/tmp/latex_work"
    os.makedirs(safe_tmp, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=safe_tmp) as tmpdir:
        tex_file = os.path.join(tmpdir, "resume.tex")
        pdf_file = os.path.join(tmpdir, "resume.pdf")

        with open(tex_file, "w", encoding="utf-8") as f:
            f.write(latex_code)

        for attempt in range(2):  # Run twice for correct rendering
            result = subprocess.run(
                [
                    pdflatex_cmd,
                    "-interaction=nonstopmode",
                    "--enable-installer",        # allow MiKTeX to auto-install missing packages
                    "-output-directory", tmpdir,
                    tex_file,
                ],
                capture_output=True,
                timeout=300,                     # 5 minutes — MiKTeX downloads packages on first run
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0 and attempt == 1:
                logger.error("pdflatex failed:\n%s", result.stdout[-3000:])
                _save_latex_fallback(latex_code, output_pdf_path)
                return False

        if os.path.exists(pdf_file):
            os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
            shutil.copy2(pdf_file, output_pdf_path)
            logger.info("Resume PDF saved: %s", output_pdf_path)
            return True

    logger.error("PDF not produced even though pdflatex returned 0.")
    return False


def save_cover_letter_pdf(cover_letter_text: str, output_pdf_path: str) -> bool:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY, TA_CENTER
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)

        doc = SimpleDocTemplate(
            output_pdf_path,
            pagesize=letter,
            leftMargin=1.91 * 0.393701 * inch,   # 1.91 cm
            rightMargin=1.91 * 0.393701 * inch,  # 1.91 cm
            topMargin=2.54 * 0.393701 * inch,    # 2.54 cm
            bottomMargin=2.54 * 0.393701 * inch, # 2.54 cm
        )

        name_style = ParagraphStyle(
            "Name", fontName="Helvetica-Bold", fontSize=11, leading=15, alignment=TA_LEFT,
        )
        contact_style = ParagraphStyle(
            "Contact", fontName="Helvetica", fontSize=10, leading=14, alignment=TA_LEFT,
        )
        body_style = ParagraphStyle(
            "Body", fontName="Helvetica", fontSize=10.5, leading=16, alignment=TA_JUSTIFY,
        )
        left_style = ParagraphStyle(
            "Left", fontName="Helvetica", fontSize=10.5, leading=16, alignment=TA_LEFT,
        )
        subject_style = ParagraphStyle(
            "Subject", fontName="Helvetica-Bold", fontSize=10.5, leading=16, alignment=TA_CENTER,
        )

        def clean(text: str) -> str:
            """Remove AI-looking characters."""
            text = text.replace("\u2014", ", ")   # em dash to comma
            text = text.replace("\u2013", "-")    # en dash to hyphen
            text = text.replace("->", ",")
            text = text.replace("=>", ",")
            text = text.replace("&", "and")
            text = text.replace("<", "")
            text = text.replace(">", "")
            return text.strip()

        # --- State machine parser ---
        lines = cover_letter_text.strip().splitlines()

        name_line     = ""
        phone_line    = ""
        email_line    = ""
        date_line     = ""
        hiring_block  = []
        subject_line  = ""
        salutation    = ""
        body_paras    = []
        closing_block = []

        STATE_HEADER  = "header"
        STATE_DATE    = "date"
        STATE_HIRING  = "hiring"
        STATE_SUBJECT = "subject"
        STATE_SALUTE  = "salute"
        STATE_BODY    = "body"
        STATE_CLOSING = "closing"

        state  = STATE_HEADER
        buffer = []

        for line in lines:
            s = line.strip()

            if state == STATE_HEADER:
                if not name_line and s:
                    name_line = s
                elif not phone_line and s.startswith("+"):
                    phone_line = s
                elif not email_line and "@" in s:
                    email_line = s
                elif s == "" and email_line:
                    state = STATE_DATE
                continue

            if state == STATE_DATE:
                if s:
                    date_line = s
                    state = STATE_HIRING
                continue

            if state == STATE_HIRING:
                if s == "":
                    if hiring_block:
                        state = STATE_SUBJECT
                else:
                    hiring_block.append(s)
                continue

            if state == STATE_SUBJECT:
                if s.lower().startswith("subject"):
                    subject_line = s
                    state = STATE_SALUTE
                elif s:
                    hiring_block.append(s)
                continue

            if state == STATE_SALUTE:
                if s.lower().startswith("dear"):
                    salutation = s
                    state = STATE_BODY
                continue

            if state == STATE_BODY:
                closing_triggers = ("warm regards", "sincerely", "best regards", "kind regards")
                if any(s.lower().startswith(t) for t in closing_triggers):
                    if buffer:
                        body_paras.append(" ".join(buffer).strip())
                        buffer = []
                    closing_block.append(s)
                    state = STATE_CLOSING
                    continue
                if s == "":
                    if buffer:
                        body_paras.append(" ".join(buffer).strip())
                        buffer = []
                else:
                    buffer.append(s)
                continue

            if state == STATE_CLOSING:
                if s:
                    closing_block.append(s)

        if buffer:
            body_paras.append(" ".join(buffer).strip())

        # --- Build PDF ---
        story = []

        if name_line:
            story.append(Paragraph(f"<b>{clean(name_line)}</b>", name_style))
        if phone_line:
            story.append(Paragraph(clean(phone_line), contact_style))
        if email_line:
            story.append(Paragraph(clean(email_line), contact_style))

        story.append(Spacer(1, 14))

        if date_line:
            story.append(Paragraph(clean(date_line), left_style))
            story.append(Spacer(1, 14))

        if hiring_block:
            for hl in hiring_block:
                story.append(Paragraph(clean(hl), left_style))
            story.append(Spacer(1, 14))
        else:
            logger.warning("Cover letter is missing company address block.")

        if subject_line:
            if ":" in subject_line:
                label, rest = subject_line.split(":", 1)
                story.append(Paragraph(f"<b>{clean(label)}:</b>{clean(rest)}", subject_style))
            else:
                story.append(Paragraph(f"<b>{clean(subject_line)}</b>", subject_style))
            story.append(Spacer(1, 14))

        if salutation:
            story.append(Paragraph(clean(salutation), left_style))
            story.append(Spacer(1, 10))

        for para in body_paras:
            if para:
                story.append(Paragraph(clean(para), body_style))
                story.append(Spacer(1, 10))

        if closing_block:
            story.append(Spacer(1, 4))
            for cl in closing_block:
                if cl.strip():
                    story.append(Paragraph(clean(cl), left_style))

        doc.build(story)
        logger.info("Cover letter PDF saved: %s", output_pdf_path)
        return True

    except Exception as e:
        logger.error("Cover letter PDF generation failed: %s", e)
        txt_path = output_pdf_path.replace(".pdf", ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(cover_letter_text)
        logger.warning("Saved plain text fallback: %s", txt_path)
        return False


def _save_latex_fallback(latex_code: str, intended_pdf_path: str):
    tex_path = intended_pdf_path.replace(".pdf", ".tex")
    os.makedirs(os.path.dirname(tex_path), exist_ok=True)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(latex_code)
    logger.warning("Saved raw LaTeX to: %s", tex_path)