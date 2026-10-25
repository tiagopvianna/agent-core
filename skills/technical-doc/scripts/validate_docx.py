#!/usr/bin/env python3

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from pathlib import Path
from xml.etree import ElementTree as ET


WORD_NS = (
    "http://schemas.openxmlformats.org/"
    "wordprocessingml/2006/main"
)

NS = {
    "w": WORD_NS,
}


REQUIRED_FILES = {
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
}


PLACEHOLDER_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"\blorem ipsum\b",
    r"\[insert\b",
    r"\{\{.+?\}\}",
]


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)


def ok(message):
    print(f"OK: {message}")


def warn(message):
    print(f"WARNING: {message}")


def validate_zip(path):
    if not zipfile.is_zipfile(path):
        fail("File is not a valid ZIP/OOXML package.")
        return None

    try:
        archive = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile:
        fail("DOCX archive is corrupted.")
        return None

    bad_file = archive.testzip()

    if bad_file:
        fail(f"Corrupted ZIP member: {bad_file}")
        archive.close()
        return None

    ok("OOXML ZIP package is valid.")

    return archive


def validate_required_files(archive):
    names = set(archive.namelist())

    missing = REQUIRED_FILES - names

    if missing:
        for name in sorted(missing):
            fail(f"Missing required OOXML file: {name}")

        return False

    ok("Required OOXML components are present.")

    return True


def parse_xml(archive, name):
    try:
        data = archive.read(name)
        return ET.fromstring(data)

    except KeyError:
        fail(f"Missing XML file: {name}")

    except ET.ParseError as exc:
        fail(f"Invalid XML in {name}: {exc}")

    return None


def validate_xml(archive):
    files_to_check = [
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
    ]

    optional = [
        "word/styles.xml",
        "word/numbering.xml",
        "word/_rels/document.xml.rels",
    ]

    for name in optional:
        if name in archive.namelist():
            files_to_check.append(name)

    valid = True

    for name in files_to_check:
        root = parse_xml(archive, name)

        if root is None:
            valid = False

    if valid:
        ok("OOXML XML files are well-formed.")

    return valid


def extract_text(archive):
    root = parse_xml(
        archive,
        "word/document.xml",
    )

    if root is None:
        return ""

    texts = []

    for node in root.findall(".//w:t", NS):
        if node.text:
            texts.append(node.text)

    return " ".join(texts).strip()


def validate_content(text):
    if not text:
        fail("Document contains no readable text.")
        return False

    word_count = len(text.split())

    if word_count < 10:
        warn(
            f"Document contains very little text "
            f"({word_count} words)."
        )
    else:
        ok(
            f"Document contains readable content "
            f"({word_count} words)."
        )

    found_placeholder = False

    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            warn(
                f"Possible placeholder detected: "
                f"{pattern}"
            )
            found_placeholder = True

    if not found_placeholder:
        ok("No obvious placeholders detected.")

    return True


def validate_embedded_media(archive):
    """Ensure every document image relationship points at a real media file."""
    rels_name = "word/_rels/document.xml.rels"
    if rels_name not in archive.namelist():
        ok("Document contains no image relationships.")
        return True

    root = parse_xml(archive, rels_name)
    if root is None:
        return False

    image_relationships = [
        rel for rel in root
        if rel.attrib.get("Type", "").endswith("/image")
    ]
    valid = True
    for rel in image_relationships:
        target = rel.attrib.get("Target", "")
        media_name = posixpath.normpath(posixpath.join("word", target))
        if media_name not in archive.namelist():
            fail(f"Image relationship points to missing media: {media_name}")
            valid = False
        elif archive.getinfo(media_name).file_size == 0:
            fail(f"Embedded image is empty: {media_name}")
            valid = False
        elif media_name.lower().endswith(".png") and archive.getinfo(media_name).file_size < 512:
            fail(f"Embedded PNG is suspiciously small and may be blank: {media_name}")
            valid = False

    if valid:
        if image_relationships:
            ok(f"Embedded images are present ({len(image_relationships)} image(s)).")
        else:
            ok("Document contains no embedded images.")

    return valid


def find_soffice():
    for executable in (
        "soffice",
        "libreoffice",
    ):
        found = shutil.which(executable)

        if found:
            return found

    return None


def render_test(path):
    soffice = find_soffice()

    if not soffice:
        fail(
            "LibreOffice/soffice not found; "
            "cannot perform render validation."
        )
        return False

    with tempfile.TemporaryDirectory() as tmp:
        command = [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmp,
            str(path.resolve()),
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )

        expected_pdf = (
            Path(tmp) / f"{path.stem}.pdf"
        )

        if result.returncode != 0:
            fail(
                "LibreOffice failed to render DOCX."
            )

            if result.stderr.strip():
                print(
                    result.stderr.strip(),
                    file=sys.stderr,
                )

            return False

        if not expected_pdf.exists():
            fail(
                "LibreOffice completed but "
                "did not produce a PDF."
            )
            return False

        if expected_pdf.stat().st_size == 0:
            fail(
                "Rendered PDF is empty."
            )
            return False

        ok(
            "LibreOffice successfully rendered "
            "the DOCX to PDF."
        )

    return True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Validate a generated DOCX file."
        )
    )

    parser.add_argument(
        "path",
        help="Path to the DOCX file.",
    )

    parser.add_argument(
        "--render",
        action="store_true",
        help=(
            "Also verify that LibreOffice "
            "can render the document."
        ),
    )

    args = parser.parse_args()

    path = Path(args.path).expanduser()

    if not path.exists():
        fail(f"File does not exist: {path}")
        sys.exit(1)

    if not path.is_file():
        fail(f"Not a file: {path}")
        sys.exit(1)

    if path.suffix.lower() != ".docx":
        fail("Expected a .docx file.")
        sys.exit(1)

    archive = validate_zip(path)

    if archive is None:
        sys.exit(1)

    valid = True

    try:
        if not validate_required_files(archive):
            valid = False

        if not validate_xml(archive):
            valid = False

        text = extract_text(archive)

        if not validate_content(text):
            valid = False

        if not validate_embedded_media(archive):
            valid = False

    finally:
        archive.close()

    if args.render:
        if not render_test(path):
            valid = False

    if not valid:
        print("\nDOCX validation FAILED.")
        sys.exit(1)

    print("\nDOCX validation PASSED.")


if __name__ == "__main__":
    main()
