#!/usr/bin/env python3
"""End-to-end smoke test. Run this first in a new environment.

    python3 tests/smoke_test.py

Builds the example course, validates it, mutates it the way a semester
rollover would, and validates the result. If this passes, the kit works and
you can trust the workflow in AGENT.md.
"""
import pathlib
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from canvas_imscc import rollforward as rf
from canvas_imscc.validate_package import check

FAILURES = []


def ok(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label + (" | " + detail if detail else ""))
    if not condition:
        FAILURES.append(label)


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cck_smoke_"))
    built = tmp / "example.imscc"

    print("\n1. Build the example course")
    r = subprocess.run([sys.executable, str(ROOT / "examples" / "build_example_course.py")],
                       capture_output=True, text=True,
                       env={"BUILD_DIR": str(tmp / "build"), "OUT": str(built),
                            "PATH": "/usr/bin:/bin"})
    ok("build script exits 0", r.returncode == 0, r.stderr.strip()[-200:])
    ok("package exists", built.exists())
    if not built.exists():
        return 1

    print("\n2. Validate it")
    problems, notes = check(built)
    for n in notes:
        print("        " + n)
    ok("no validation problems", not problems, "; ".join(problems[:3]))

    with zipfile.ZipFile(built) as z:
        man = z.read("imsmanifest.xml").decode()
        names = set(z.namelist())
    ok("course_settings declared as a resource",
       'href="course_settings/canvas_export.txt"' in man)
    ok("assignments are their own root folders, not wiki_content",
       any(n.endswith("/assignment_settings.xml") and not n.startswith("wiki_content")
           for n in names))

    print("\n3. Path encoding helpers")
    p = "web_resources/Presentations & PDFs/Dec 15, 2021.pdf"
    spellings = rf.path_spellings(p)
    ok("plain spelling included", p in spellings)
    ok("xml-escaped spelling included",
       "web_resources/Presentations &amp; PDFs/Dec 15, 2021.pdf" in spellings)
    ok("Canvas-style encoding keeps commas literal",
       any("Dec%2015,%202021" in s for s in spellings),
       "Canvas does not encode commas the way urllib does")
    ok("longest first, so a plain spelling cannot eat an escaped one",
       spellings == sorted(spellings, key=len, reverse=True))
    ok("xml_href escapes ampersands",
       rf.xml_href("a & b") == "a &amp; b")
    ok("html_href percent-encodes then escapes",
       rf.html_href("a & b") == "a%20&amp;%20b", rf.html_href("a & b"))

    print("\n4. apply_remap emits one encoding, not a pairwise swap")
    # The bug this prevents: source has no ampersand, destination does, so a
    # plain-to-plain replacement writes a bare & into XML and breaks it.
    xml = '<resource href="unfiled/x.pdf"/>'
    out = rf.apply_remap(xml, {"unfiled/x.pdf": "Syllabi & Schedules/x.pdf"}, "xml")
    ok("no bare ampersand written into XML", " & " not in out, out)
    ok("ampersand is escaped", "&amp;" in out, out)

    print("\n5. Due dates")
    due, local, allday = rf.due_fields("2026-03-12", utc_offset=4)
    ok("all-day EDT lands next UTC day at hour offset-1",
       (due, local, allday) == ("2026-03-13T03:59:59", "2026-03-12", "true"), due)
    due, local, allday = rf.due_fields("2026-02-19", utc_offset=5)
    ok("all-day EST lands next UTC day at hour offset-1",
       (due, local, allday) == ("2026-02-20T04:59:59", "2026-02-19", "true"), due)
    due, _, allday = rf.due_fields("2026-09-08", clock="14:00", utc_offset=4)
    ok("timed deadline stays on the same UTC day",
       (due, allday) == ("2026-09-08T18:00:00", "false"), due)
    try:
        rf.due_fields("2026-09-08")
        ok("missing utc_offset raises", False)
    except ValueError:
        ok("missing utc_offset raises", True)

    print("\n6. Mutate the package the way a rollover would")
    rolled = tmp / "rolled.imscc"
    with zipfile.ZipFile(built) as z:
        page = next(n for n in z.namelist() if n.startswith("wiki_content/"))
        body = z.read(page).decode()
    rf.stream_rewrite(built, rolled,
                      replace={page: body.replace("</body>", "<p>Fall 2026</p></body>",
                                                  1).encode()},
                      add={"web_resources/extra.txt": b"hello"})
    rf.assert_xml_parses(rolled)
    ok("mutated package parses", True)
    added, removed, modified = rf.diff_packages(built, rolled)
    ok("diff sees exactly one addition", added == ["web_resources/extra.txt"], str(added))
    ok("diff sees exactly one modification", modified == [page], str(modified))
    ok("diff sees no removals", removed == [], str(removed))

    print("\n7. The validator actually catches a broken package")
    broken = tmp / "broken.imscc"
    rf.stream_rewrite(built, broken,
                      replace={"imsmanifest.xml": man.replace(
                          "<resources>", "<resources & >", 1).encode()})
    problems, _ = check(broken)
    ok("malformed XML is reported",
       any("not well-formed" in p for p in problems), str(problems[:1]))

    undeclared = tmp / "undeclared.imscc"
    rf.stream_rewrite(built, undeclared,
                      replace={"imsmanifest.xml": man.replace(
                          'href="course_settings/canvas_export.txt"',
                          'href="course_settings/nope.txt"', 1).encode()})
    problems, _ = check(undeclared)
    ok("undeclared course_settings is reported",
       any("NOT declared" in p for p in problems), str(problems[:1]))

    print("\n8. Personal-data sweep finds a name in a page body")
    problems, _ = check(built, ["Firstname"])
    ok("name in a file body is reported",
       any("Firstname" in p for p in problems), str(problems[:1]))

    print()
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    print("scratch dir: %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
