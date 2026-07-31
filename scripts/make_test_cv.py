#!/usr/bin/env python3
"""Generate the test-fixture CV PDF used by the scout tests.

Hand-rolled rather than reportlab-generated: the fixture only needs a few lines
of *extractable* text, and adding a PDF-authoring library to the dev deps just
to produce a 2KB file that changes once a year is not worth it. The previous
fixture (dashboard/tests/fixtures/dummy-cv.pdf) was a valid PDF with no text
objects at all, so pypdf extracted "" from it and every profile built from it
had zero skills -- a fixture that could not fail when the matching logic broke.

    python scripts/make_test_cv.py [output.pdf]
"""

from __future__ import annotations

import sys
from pathlib import Path

DEFAULT_OUT = (Path(__file__).resolve().parent.parent
               / "dashboard" / "tests" / "fixtures" / "test-cv.pdf")

# Deliberately mentions skills the lexicon knows (.NET, C#, Azure, Kafka,
# Kubernetes, microservices, backend, tech lead) so a profile built from it is
# non-empty and the scoring path is actually exercised.
LINES = [
    "Alex Muster - Senior Backend Software Engineer",
    "Vienna, Austria | alex.muster@example.com",
    "",
    "Summary",
    "Backend engineer with 10 years building distributed systems.",
    "Tech lead for a team of six.",
    "",
    "Skills",
    ".NET / C# / ASP.NET, Azure, Kafka, Kubernetes, Docker",
    "microservices, distributed systems, SQL, PostgreSQL",
    "Python, TypeScript, Angular, CI/CD, DevOps, Terraform",
    "",
    "Experience",
    "Senior Software Engineer, ACME GmbH, Vienna (2020-2026)",
    "Built event-driven microservices on Azure with Kafka and Kubernetes.",
    "Software Developer, Beta AG, Vienna (2016-2020)",
    "ASP.NET Core backend services, SQL Server, Docker.",
]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(lines: list[str]) -> bytes:
    """Minimal single-page PDF with a Helvetica text block."""
    body = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
    for line in lines:
        body.append(f"({_escape(line)}) Tj" if line else "()  Tj")
        body.append("T*")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_pdf(LINES))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
