import fitz


def extract_text_from_pdf_bytes(file_bytes: bytes) -> str:
    """Extract text from a PDF file represented as bytes."""
    document = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []

    for page_number, page in enumerate(document, start=1):
        text = page.get_text("text")
        pages.append(f"\n--- Page {page_number} ---\n{text}")

    return "\n".join(pages).strip()
