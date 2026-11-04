"""Turn an uploaded PDF or DOCX into plain text (shown back to the professor, US-5)."""


def extract_text(data: bytes, filename: str) -> str:
    # TODO: .pdf → LAYOUT-PRESERVING extraction (pypdf: page.extract_text(extraction_mode="layout"),
    #       or pdftotext -layout). The default mode scrambles table rows, and syllabus schedules
    #       are tables. Then collapse runs of 3+ spaces to " | " (keeps columns, saves tokens).
    #       See agent/eval/try_structure.py:extract for the version tested on PHC 6149.
    #       .docx → python-docx (paragraphs + tables, cells joined with " | "); .txt → decode
    #       Raise ValueError("unreadable") if fewer than 500 readable characters.
    raise NotImplementedError
