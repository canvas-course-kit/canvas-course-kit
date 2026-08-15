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
import xml.etree.ElementTree as ET
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


def z_read(path, name):
    import zipfile
    with zipfile.ZipFile(path) as z:
        return z.read(name)


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

    print("\n6b. Path encodings taken from a real Canvas export")
    # Both of these appear verbatim in real exports and were missed by
    # generating candidate spellings.
    quoted = 'web_resources/Rikard &quot;Color Harmony&quot; (2015).pdf'
    coloned = "Project%201:%20Notes/rock.gif"
    ok("a &quot; href spelling is generated",
       quoted in rf.path_spellings(
           'web_resources/Rikard "Color Harmony" (2015).pdf'), quoted)
    ok("Canvas's literal colon spelling is generated",
       coloned in rf.path_spellings("Project 1: Notes/rock.gif"), coloned)

    ok("xml_href escapes a double quote",
       rf.xml_href('a "b".pdf') == "a &quot;b&quot;.pdf", rf.xml_href('a "b".pdf'))
    ok("xml_href leaves an apostrophe literal (Canvas never writes &#x27;)",
       rf.xml_href("Ocean's.pdf") == "Ocean's.pdf", rf.xml_href("Ocean's.pdf"))

    moved = {'Rikard "Color Harmony" (2015).pdf': 'Refs/Rikard "Color Harmony" (2015).pdf',
             "Project 1: Notes/rock.gif": "Project 1 - Notes/rock.gif"}
    xml_in = '<file href="web_resources/Rikard &quot;Color Harmony&quot; (2015).pdf"/>'
    xml_out = rf.remap_references(xml_in, moved, "xml")
    ok("remap_references rewrites a &quot; path",
       "Refs/Rikard &quot;" in xml_out, xml_out)
    try:
        ET.fromstring(xml_out)
        wf = True
    except ET.ParseError as e:
        wf = str(e)
    ok("and leaves the XML well-formed", wf is True, str(wf))

    html_in = '<img src="$IMS-CC-FILEBASE$/Project%201:%20Notes/rock.gif"/>'
    ok("remap_references rewrites a literal-colon path",
       "Project%201%20-%20Notes/rock.gif" in
       rf.remap_references(html_in, moved, "html"),
       rf.remap_references(html_in, moved, "html"))
    untouched = '<file href="web_resources/Not Moved.pdf"/>'
    ok("a path that is not moving is left exactly alone",
       rf.remap_references(untouched, moved, "xml") == untouched, untouched)

    print("\n7b. Content added to module_meta but not <organizations>")
    # Canvas builds the module tree from <organizations>. A module present
    # only in module_meta is not malformed and not dangling, it just does not
    # import. This is the check that would have caught a whole missing module.
    meta = z_read(built, "course_settings/module_meta.xml").decode()
    ghost = meta.replace(
        "</modules>",
        '  <module identifier="gGHOSTMODULE0000000000000000000">\n'
        "    <title>GHOST MODULE</title>\n"
        "    <workflow_state>active</workflow_state>\n"
        "    <position>99</position>\n"
        "    <items>\n"
        '      <item identifier="gGHOSTITEM00000000000000000000">\n'
        "        <content_type>WikiPage</content_type>\n"
        "        <title>GHOST ITEM</title>\n"
        "      </item>\n"
        "    </items>\n"
        "  </module>\n</modules>", 1)
    ghosted = tmp / "ghost.imscc"
    rf.stream_rewrite(built, ghosted,
                      replace={"course_settings/module_meta.xml": ghost.encode()})
    problems, _ = check(ghosted)
    ok("module missing from <organizations> is reported",
       any("GHOST MODULE" in p and "<organizations>" in p for p in problems),
       str(problems[:2]))
    ok("module ITEM missing from <organizations> is reported",
       any("GHOST ITEM" in p and "<organizations>" in p for p in problems),
       str(problems[:2]))

    print("\n7c. Dangling links are found outside .html too")
    # A discussion stores its body as escaped HTML inside its own .xml, so a
    # checker that only reads .html cannot see a broken link in an
    # announcement.
    disc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<topic xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1">\n'
            "  <title>Announcement</title>\n"
            '  <text texttype="text/html">&lt;img src="$IMS-CC-FILEBASE$/'
            'gone.png"&gt;</text>\n</topic>\n')
    withdisc = tmp / "withdisc.imscc"
    rf.stream_rewrite(built, withdisc, add={"gDISCUSSION1.xml": disc.encode()})
    problems, _ = check(withdisc)
    ok("dangling link inside a discussion .xml is reported",
       any("gone.png" in p for p in problems), str(problems[:2]))

    # ...but a discussion body is escaped HTML inside XML, i.e. two layers.
    # Unescaping only once leaves "A&amp;D" and reports a file that is present
    # as missing. This was a false positive on a real export.
    amp = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<topic xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1">\n'
           "  <title>Announcement</title>\n"
           '  <text texttype="text/html">&lt;a href="$IMS-CC-FILEBASE$/'
           'A&amp;amp;D.pdf"&gt;x&lt;/a&gt;</text>\n</topic>\n')
    ampzip = tmp / "amp.imscc"
    rf.stream_rewrite(built, ampzip,
                      add={"gDISC2.xml": amp.encode(),
                           "web_resources/A&D.pdf": b"%PDF-1.4\n"})
    problems, _ = check(ampzip)
    ok("a double-escaped link to a file that EXISTS is not reported",
       not any("A&" in p and "dangling" in p for p in problems),
       str([p for p in problems if "dangling" in p][:2]))

    print("\n7d. Unweighted assignment groups are not an error")
    groups = z_read(built, "course_settings/assignment_groups.xml").decode()
    unweighted = re.sub(r"<group_weight>[\d.]+</group_weight>",
                        "<group_weight>0.0</group_weight>", groups)
    flat = tmp / "unweighted.imscc"
    rf.stream_rewrite(built, flat,
                      replace={"course_settings/assignment_groups.xml":
                               unweighted.encode()})
    problems, notes2 = check(flat)
    ok("all-zero group weights are not reported as a problem",
       not any("weights sum to" in p for p in problems), str(problems[:2]))
    ok("unweighted gradebook is noted instead",
       any("unweighted" in n for n in notes2), str(notes2[:3]))

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
