"""Generate small deterministic PDF fixtures without external PDF-writing dependencies."""

from __future__ import annotations

from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content_stream(columns: list[list[str]]) -> bytes:
    commands: list[str] = []
    for column_index, lines in enumerate(columns):
        x = 72 if column_index == 0 else 320
        commands.extend(["BT", "/F1 11 Tf", f"{x} 760 Td"])
        for line_index, line in enumerate(lines):
            if line_index:
                commands.append("0 -17 Td")
            commands.append(f"({_escape_pdf_text(line)}) Tj")
        commands.append("ET")
    return "\n".join(commands).encode("ascii")


def write_pdf(path: Path, pages: list[list[list[str]]]) -> None:
    """Write a text-only PDF with exact page objects suitable for pdfplumber tests."""

    font_number = 3 + len(pages) * 2
    page_numbers = [3 + index * 2 for index in range(len(pages))]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Count {len(pages)} /Kids "
            f"[{' '.join(f'{number} 0 R' for number in page_numbers)}] >>"
        ).encode("ascii"),
    ]
    for index, columns in enumerate(pages):
        page_number = page_numbers[index]
        content_number = page_number + 1
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
                f"/Contents {content_number} 0 R >>"
            ).encode("ascii")
        )
        content = _content_stream(columns)
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n%CellWiki fixture\n")
    offsets = [0]
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(output)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    write_pdf(
        FIXTURES / "page_aware_source.pdf",
        [
            [["INTRODUCTION", "Regulatory T cell identity was examined."]],
            [["RESULTS", "Regulatory T cell expressed FOXP3 as a positive marker in tumor tissue."]],
            [["DISCUSSION", "The evidence is context dependent."]],
        ],
    )
    write_pdf(
        FIXTURES / "two_column_source.pdf",
        [
            [
                ["LEFT COLUMN", "Regulatory T cell", "FOXP3 positive"],
                ["RIGHT COLUMN", "CD8 T cell", "PDCD1 positive"],
            ],
            [["RESULTS", "Columns remain on the same numbered PDF page."]],
        ],
    )
    write_pdf(
        FIXTURES / "long_52_page_source.pdf",
        [
            [[f"PAGE {page}", f"Regulatory T cell evidence on page {page}."]]
            for page in range(1, 53)
        ],
    )


if __name__ == "__main__":
    main()
