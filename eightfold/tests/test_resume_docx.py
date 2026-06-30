"""Proves the dependency-free .docx path: a .docx is a zip of XML, and our resume extractor
reads it with only the standard library (no python-docx)."""
import zipfile

from transformer.extractors.resume import ResumeExtractor

_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_docx(path, paragraphs):
    """Write a minimal-but-valid .docx containing the given paragraphs."""
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_NS}"><w:body>{body}</w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", document)


def test_docx_resume_is_parsed(tmp_path):
    docx = tmp_path / "grace.docx"
    _make_docx(docx, [
        "Grace Hopper",
        "grace@navy.mil | github.com/grace-h",
        "Skills",
        "COBOL, Compilers, C++",
        "Experience",
        "Senior Engineer, US Navy (1944-01 - 1986-08)",
        "Education",
        "Yale University, PhD in Mathematics, 1934",
    ])

    records = ResumeExtractor().extract(str(docx))
    assert len(records) == 1
    fields = {c.field for c in records[0].claims}
    assert "full_name" in fields and "emails" in fields and "skills" in fields


def test_corrupt_docx_does_not_crash(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"this is not a real zip/docx")
    assert ResumeExtractor().extract(str(bad)) == []  # graceful, no exception
