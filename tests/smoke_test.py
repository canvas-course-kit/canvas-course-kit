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
from canvas_imscc import accessibility as a11y
from canvas_imscc import privacy as priv

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

    # A file in the zip that no resource declares. This is what a rebuild into
    # a dirty build directory leaves behind (add_page_resource renames rather
    # than overwrites, zip_package zips the whole folder), and it passed every
    # check the kit had until a package shipped 193 entries for 79 resources.
    orphaned = tmp / "orphaned.imscc"
    rf.stream_rewrite(built, orphaned, add={"wiki_content/leftover-2.html": b"<html/>"})
    problems, _ = check(orphaned)
    ok("an undeclared file in the zip is reported",
       any("declared by no resource" in p for p in problems), str(problems[:1]))

    # And the check must not fire on course_settings/, which real Canvas
    # exports fill with files their resource does not list.
    extra_settings = tmp / "extra_settings.imscc"
    rf.stream_rewrite(built, extra_settings,
                      add={"course_settings/late_policy.xml": b"<late_policy/>"})
    problems, notes_es = check(extra_settings)
    ok("an undeclared course_settings file is a note, not a failure",
       not any("declared by no resource" in p for p in problems)
       and any("late_policy" in n for n in notes_es), str(problems[:1]) + str(notes_es))

    print("\n7c. The syllabus, page links, and the build-time orphan check")
    from canvas_imscc.builder import ImsccBuilder
    import xml.etree.ElementTree as _ET

    sb = tmp / "syl_build"
    b2 = ImsccBuilder("Syllabus Course", sb, canvas_domain="x.instructure.com",
                      root_account_name="U")
    m2 = b2.new_module("M")
    # A link written BEFORE the target page exists, which is the case that
    # cannot be handled by passing an id around.
    rid_a = b2.add_page_resource(
        "Alpha", '<p>See <a href="%s">Beta</a> and <a href="%s">its middle</a>.</p>'
        % (b2.page_link("Beta"), b2.page_link("Beta", anchor="middle")))
    rid_b = b2.add_page_resource("Beta", "<p>b</p>")
    b2.add_item(m2, "WikiPage", "Alpha", resource_id=rid_a)
    b2.add_item(m2, "WikiPage", "Beta", resource_id=rid_b)
    b2.add_syllabus("<p>Come to class.</p>")
    b2.write_manifest_and_settings()
    ok2, rep2 = b2.validate()
    ok("validate() accepts a package carrying a syllabus", ok2, rep2)

    syl_pkg = tmp / "syllabus.imscc"
    b2.zip_package(syl_pkg)
    with zipfile.ZipFile(syl_pkg) as z:
        man2 = z.read("imsmanifest.xml").decode()
        alpha = z.read([n for n in z.namelist() if n.endswith("alpha.html")][0]).decode()
        syl_in_zip = "course_settings/syllabus.html" in z.namelist()
    ok("syllabus.html is in the package", syl_in_zip)
    ok("syllabus is declared with intendeduse", 'intendeduse="syllabus"' in man2,
       man2[:0])
    ok("syllabus resource id is derived from course_settings",
       '%s_syllabus' % b2.course_settings_resource_id in man2)
    ok("a forward page link resolved to the real resource id",
       "$WIKI_REFERENCE$/pages/%s" % rid_b in alpha, alpha)
    ok("an anchored page link keeps its query delimiter",
       "/pages/%s?titleize=0#middle" % rid_b in alpha, alpha)
    ok("no placeholder survived", "@@" not in alpha, alpha)
    problems, _ = check(syl_pkg)
    ok("the finished syllabus package validates", not problems, str(problems[:2]))

    # A link naming a page nobody added must stop the build.
    b3 = ImsccBuilder("Bad Links", tmp / "bad_build", canvas_domain="x.instructure.com",
                      root_account_name="U")
    m3 = b3.new_module("M")
    b3.add_item(m3, "WikiPage", "A",
                resource_id=b3.add_page_resource(
                    "A", '<a href="%s">x</a>' % b3.page_link("Nonexistent")))
    try:
        b3.write_manifest_and_settings()
        ok("a link to a page that was never added fails the build", False, "no error")
    except ValueError as exc:
        ok("a link to a page that was never added fails the build",
           "Nonexistent" in str(exc), str(exc)[:120])

    # The validator must reject the two link forms that do not resolve.
    for bad, why in ((("$WIKI_REFERENCE$/wiki_pages/aquatint"), "wiki_pages is not a route"),
                     (("$WIKI_REFERENCE$/pages/%s#middle" % rid_b), "undelimited fragment")):
        pkg = tmp / ("badlink%d.imscc" % abs(hash(bad)) )
        rf.stream_rewrite(syl_pkg, pkg, transform=lambda n, d, bad=bad: (
            d.replace(b"$WIKI_REFERENCE$/pages/" + rid_b.encode(), bad.encode())
            if n.endswith("alpha.html") else d))
        problems, _ = check(pkg)
        ok("the validator rejects %s" % why,
           any("$WIKI_REFERENCE$" in p for p in problems), str(problems[:2]))

    # Building twice into the same directory must fail rather than ship the
    # stale copy. This is issue #6's other half: the validator catches it in
    # the finished package, this catches it before the package exists.
    b4 = ImsccBuilder("Rebuilt", sb, canvas_domain="x.instructure.com",
                      root_account_name="U")
    m4 = b4.new_module("M")
    b4.add_item(m4, "WikiPage", "Alpha",
                resource_id=b4.add_page_resource("Alpha", "<p>again</p>"))
    b4.write_manifest_and_settings()
    try:
        b4.zip_package(tmp / "rebuilt.imscc")
        ok("a rebuild into a dirty directory fails at zip time", False, "no error")
    except ValueError as exc:
        ok("a rebuild into a dirty directory fails at zip time",
           "declared by no resource" in str(exc), str(exc)[:120])

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

    print("\n7e. Rubric arithmetic: the two ways a criteria rewrite goes wrong")
    # Neither of these is malformed, dangling, or visible in the cartridge
    # viewer. Both import clean and only surface when someone grades.
    rubrics = z_read(built, "course_settings/rubrics.xml")
    root = ET.fromstring(rubrics)
    CCX = "{http://canvas.instructure.com/xsd/cccv1p0}"

    # (a) the naive rewrite: zip the new list against the old elements. Going
    #     from three criteria to four drops the fourth on the floor.
    naive = ET.fromstring(rubrics)
    want = [("Process", 30.0), ("Execution", 30.0),
            ("Engagement", 20.0), ("Research", 20.0)]
    rub = naive[0]
    holder = rub.find(CCX + "criteria")
    for i, (desc, pts) in enumerate(want):
        old = list(holder)
        if i >= len(old):
            continue                     # <- the bug, written out plainly
        old[i].find(CCX + "description").text = desc
        old[i].find(CCX + "points").text = "%.1f" % pts
    dropped = tmp / "rubric-dropped.imscc"
    rf.stream_rewrite(built, dropped,
                      replace={"course_settings/rubrics.xml": ET.tostring(naive)})
    problems, _ = check(dropped)
    ok("a silently dropped criterion is reported",
       any("criteria sum to" in p for p in problems), str(problems[:2]))

    # (b) the criterion is repointed but its rating scale keeps last term's
    #     numbers, so a 30-point criterion still tops out at 40.
    stale = ET.fromstring(rubrics)
    c0 = stale[0].find(CCX + "criteria")[0]
    c0.find(CCX + "points").text = "30.0"
    scaled = tmp / "rubric-stale-scale.imscc"
    rf.stream_rewrite(built, scaled,
                      replace={"course_settings/rubrics.xml": ET.tostring(stale)})
    problems, _ = check(scaled)
    ok("a rating scale left on the old maximum is reported",
       any("tops out at" in p for p in problems), str(problems[:2]))

    # (c) rewrite_rubric() does the same edit correctly: four criteria out of
    #     three, every rating rescaled, and it still validates.
    fixed = ET.fromstring(rubrics)
    rf.rewrite_rubric(fixed[0], want, title="Project Rubric, Fall 2026")
    crits = fixed[0].findall(".//" + CCX + "criterion")
    ok("rewrite_rubric keeps the added criterion", len(crits) == 4, str(len(crits)))
    tops = [max(float(r.findtext(CCX + "points"))
                for rat in c.findall(CCX + "ratings") for r in rat) for c in crits]
    ok("rewrite_rubric rescales every rating scale",
       tops == [30.0, 30.0, 20.0, 20.0], str(tops))
    good = tmp / "rubric-fixed.imscc"
    rf.stream_rewrite(built, good,
                      replace={"course_settings/rubrics.xml": ET.tostring(fixed)})
    problems, _ = check(good)
    ok("the corrected rubric validates clean",
       not any("rubric" in p for p in problems), str(problems[:2]))

    # (d) and it refuses to write a rubric that does not add up at all.
    try:
        rf.rewrite_rubric(ET.fromstring(rubrics)[0], [("Only", 10.0)])
        raised = False
    except SystemExit:
        raised = True
    ok("rewrite_rubric refuses criteria that miss points_possible", raised)

    print("\n8. Personal-data sweep finds a name in a page body")
    problems, _ = check(built, ["Firstname"])
    ok("name in a file body is reported",
       any("Firstname" in p for p in problems), str(problems[:1]))

    print("\n9. Accessibility checks fire, and do not fire on clean HTML")

    # A page that is genuinely fine. If this produces findings the checker is
    # crying wolf, which is worse than not shipping it: people switch off a
    # validator that flags correct work.
    clean = """
    <h2>Week One</h2>
    <p>Read the <a href="/ch1">Nicolaides chapter on gesture</a> first.</p>
    <img src="g.jpg" alt="A gesture drawing in vine charcoal, arm extended">
    <h3>Materials</h3>
    <ul><li>Vine charcoal</li></ul>
    <table><caption>Schedule</caption>
      <tr><th scope="col">Week</th><th scope="col">Topic</th></tr>
      <tr><td>1</td><td>Gesture</td></tr></table>
    <p style="color:#333333">A readable note.</p>"""
    ok("clean page produces no findings", not a11y.audit_html(clean, "clean"),
       str([str(f) for f in a11y.audit_html(clean, "clean")][:3]))

    # One deliberately broken page per check. Each entry is (code, html).
    cases = [
        ("img-no-alt", '<img src="p.jpg">'),
        ("img-alt-filename",
         '<img src="a.png" alt="Screen%20Shot%202024-01-02.png">'),
        ("img-alt-vague", '<img src="a.png" alt="image">'),
        ("heading-skipped-level", "<h2>A</h2><h4>B</h4>"),
        ("heading-empty", "<h2></h2>"),
        ("heading-h1-in-body", "<h1>Title</h1>"),
        ("heading-faked-with-bold", "<p><strong>Supplies</strong></p>"),
        ("link-text-meaningless", '<a href="/x">click here</a>'),
        ("link-no-text", '<a href="/x"></a>'),
        ("link-text-is-url", '<a href="/x">https://example.com/a/b</a>'),
        ("table-no-headers", "<table><tr><td>1</td></tr><tr><td>2</td></tr></table>"),
        ("table-th-no-scope", "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"),
        ("iframe-no-title", '<iframe src="https://player.vimeo.com/1"></iframe>'),
        ("media-captions-unverifiable",
         '<iframe title="Lecture" src="https://youtube.com/embed/x"></iframe>'),
        ("contrast-too-low", '<p style="color:#bbbbbb">grey on white</p>'),
        ("list-faked-with-text", "<p>- vine charcoal</p>"),
    ]
    for code, html in cases:
        codes = {f.code for f in a11y.audit_html(html, "case")}
        ok("a11y check fires: %s" % code, code in codes, str(sorted(codes)))

    # Contrast has to be right, not merely present. #767676 on white is the
    # textbook 4.5:1 boundary, so it must pass while one shade lighter fails.
    ok("contrast: #767676 on white passes",
       not [f for f in a11y.audit_html('<p style="color:#767676">x</p>', "c")
            if f.code == "contrast-too-low"])
    ok("contrast: #777777 on white fails",
       [f for f in a11y.audit_html('<p style="color:#777777">x</p>', "c")
        if f.code == "contrast-too-low"])
    # Large text has a lower bar, and applying the body threshold to headings
    # would flag legitimate design.
    ok("contrast: large text uses the 3:1 threshold",
       not [f for f in a11y.audit_html(
            '<h2 style="color:#949494">Big</h2>', "c")
            if f.code == "contrast-too-low"])

    # Parsing, not pattern-matching: an alt attribute containing ">" is valid
    # HTML that a regex-based checker reports as a missing alt.
    ok("a11y does not false-positive on > inside an attribute",
       not a11y.audit_html('<img src="x.jpg" alt="width > height, in chalk">', "c"))

    # A parser that dies must REPORT, not return []. An empty finding list
    # reads exactly like a clean page, which is this repo's oldest failure
    # mode: a check that passes while nothing was actually checked. Force the
    # failure by breaking the parser rather than trusting the guard by eye.
    _real_feed = a11y._Collector.feed
    a11y._Collector.feed = lambda self, data: (_ for _ in ()).throw(
        RuntimeError("boom"))
    try:
        codes = {f.code for f in a11y.audit_html("<p>anything</p>", "broken")}
    finally:
        a11y._Collector.feed = _real_feed
    ok("a parser failure is reported, not swallowed",
       "html-unparseable" in codes, str(sorted(codes)))

    # Bodies escaped inside <text texttype="text/html"> are audited too.
    # Discussions and announcements live there, and a checker that only opens
    # .html gives every discussion in the course a free pass.
    disc = ('<?xml version="1.0"?><topic><text texttype="text/html">'
            '&lt;img src="x.jpg"&gt;&lt;a href="/y"&gt;click here&lt;/a&gt;'
            '</text></topic>')
    bodies = list(a11y._escaped_bodies(disc))
    found = set()
    for b in bodies:
        found |= {f.code for f in a11y.audit_html(b, "disc")}
    ok("html escaped inside a discussion .xml is audited",
       {"img-no-alt", "link-text-meaningless"} <= found, str(sorted(found)))

    # PDFs are reported, never rewritten.
    minimal_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<<>>"
    codes = {f.code for f in a11y.audit_pdf(minimal_pdf, "x.pdf")}
    ok("untagged pdf is reported", "pdf-untagged" in codes, str(sorted(codes)))
    tagged = b"%PDF-1.4\n1 0 obj<</Type/Catalog/StructTreeRoot 2 0 R/Lang(en-US)>>"
    codes = {f.code for f in a11y.audit_pdf(tagged, "y.pdf")}
    ok("tagged pdf with a language is not reported as untagged",
       "pdf-untagged" not in codes and "pdf-no-language" not in codes,
       str(sorted(codes)))

    # The shipped example must itself be clean, or the kit is teaching the
    # markup it flags. This is the check that keeps it that way.
    ex_findings, _ = a11y.audit_package(built)
    ok("the example course has no accessibility findings", not ex_findings,
       str([str(f) for f in ex_findings][:3]))

    # The package-level summary must not change exit status on its own.
    problems, notes = check(built)
    ok("accessibility appears in the validator's notes",
       any(n.startswith("accessibility:") for n in notes),
       str([n for n in notes if n.startswith("accessibility")]))
    ok("accessibility findings are NOT structural problems",
       not any("accessibility" in p for p in problems))

    print("\n10. Reading an export: the two things that caused a false diagnosis")

    # (a) The package's date must be reported. Several exports of one course
    #     live in one folder and look alike, and a course has been declared
    #     broken on the evidence of one that simply predated the fix.
    _, notes = check(built)
    ok("validate_package reports when the package was built",
       any(n.startswith("package built ") for n in notes),
       str([n for n in notes if n.startswith("package built")]))

    # (b) An assignment that exists but sits in NO module contributes zero
    #     <content_type>Assignment</> lines to module_meta.xml, because that
    #     file records module membership and nothing else. Reading that zero as
    #     "they all imported as Pages" is wrong, and looks exactly like the
    #     rule 2 failure. Strip the Assignment items out of module_meta and the
    #     validator must still say the assignments are there and fine.
    meta = z_read(built, "course_settings/module_meta.xml").decode()
    item_re = (r'\s*<item identifier="[^"]+">'
               r'(?:(?!</item>).)*?'
               r'<content_type>Assignment</content_type>.*?</item>')
    stripped = re.sub(item_re, '', meta, flags=re.S)
    ok("test fixture actually removed the Assignment module items",
       stripped.count("<content_type>Assignment</content_type>") == 0
       and stripped != meta)
    unmoduled = tmp / "assignments-not-in-modules.imscc"
    rf.stream_rewrite(built, unmoduled,
                      replace={"course_settings/module_meta.xml":
                               stripped.encode()})
    problems, notes = check(unmoduled)
    ok("assignments outside every module are NOT reported as a problem",
       not problems, str(problems[:2]))
    ok("the note says they exist and are gradeable",
       any("not linked from" in n and "NOT evidence" in n for n in notes),
       str([n for n in notes if "assignment(s)" in n]))

    print("\n11. The student-data sweep flags, and does not block")

    ok("a clean package flags nothing", not priv.audit_privacy(built)[0],
       str([str(f) for f in priv.audit_privacy(built)[0]][:2]))

    # Each detector, one at a time. The capitalisation in the filename and
    # upload patterns is load-bearing: compiling either case-insensitively
    # made "Antonio Lopez Garcia, Sick, charcoal.jpg" read as a student named
    # Sick Charcoal, which is how that bug was found.
    import os as _os
    checks = [
        ("BAD_PATH fires on a submissions folder",
         priv.BAD_PATH.search("submissions/g1/drawing.pdf")),
        ("BAD_PATH fires on a gradebook csv",
         priv.BAD_PATH.search("web_resources/Grades-ART226.csv")),
        ("BAD_PATH ignores an ordinary article",
         not priv.BAD_PATH.search("web_resources/Articles/A_Case_for_Drawing.pdf")),
        ("BAD_PATH ignores a page about student resources",
         not priv.BAD_PATH.search("wiki_content/ut-student-resources.html")),
        ("submission filename convention fires",
         priv.STUDENT_FILE.search("ART226_Jane_Doe.pdf")),
        ("'Lastname, Firstname.jpg' fires",
         priv.STUDENT_FILE.search("Doe, Jane.jpg")),
        ("an artwork credit does NOT fire",
         not priv.STUDENT_FILE.search("Antonio Lopez Garcia, Sick, charcoal.jpg")),
        ("a reading filename does NOT fire",
         not priv.STUDENT_FILE.search("A_Case_for_Drawing.pdf")),
        ("user records fire",
         priv.USER_ELEMENT.search("<user_id>442</user_id>")),
        ("assignment settings do NOT fire",
         not priv.USER_ELEMENT.search("<grader_count>3</grader_count>")),
        ("submission_types does NOT fire",
         not priv.USER_ELEMENT.search("<submission_types>online</submission_types>")),
        ("a Canvas Student app upload name fires",
         priv.CANVAS_UPLOAD.search("Nicole Rodriguez - Dec 15, 2021 1142 AM - x.jpg")),
        ("an artist name alone does NOT fire",
         not priv.CANVAS_UPLOAD.search("Diane Victor, Shadow Boxer, charcoal")),
        ("an email address is found",
         priv.EMAIL.findall("write to someone@example.edu today")),
    ]
    for label, cond in checks:
        ok("privacy: " + label, bool(cond))

    # And the whole point: it must never change an exit status.
    ok("privacy findings are not structural problems",
       not any("student data" in p for p in check(built)[0]))
    ok("the privacy CLI exits 0 even when it flags things",
       priv.main([str(built)]) == 0)

    print("\n12. A targeted package may reference the live course's assignment groups")

    from canvas_imscc.builder import ImsccBuilder
    for external, expect_ok in ((False, False), (True, True)):
        bb = ImsccBuilder("T", tmp / ("extgrp-%s" % external),
                          external_assignment_groups=external)
        bb.add_assignment_resource("A", "<p>x</p>", "gLIVEGROUPFROMTHECOURSE")
        bb.write_manifest_and_settings()
        got_ok, rep = bb.validate()
        ok("external_assignment_groups=%s -> validate ok is %s"
           % (external, expect_ok), got_ok is expect_ok, rep.splitlines()[-1])
    # The False case above is the one that matters: an assignment with no
    # declared group is still a hard failure by default, because Canvas
    # silently reweights a gradebook. The opt-out has to be asked for.

    print()
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    print("scratch dir: %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
