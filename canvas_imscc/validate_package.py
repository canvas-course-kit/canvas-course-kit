#!/usr/bin/env python3
"""Check a finished .imscc before you import it.

Works on ANY package: one built with builder.py, one produced by mutating a
real export, or a real Canvas export you want to inspect. It opens the zip
and reasons about what is actually in it, so it does not care how the file
was made.

    python3 -m canvas_imscc.validate_package "My Course.imscc"
    python3 -m canvas_imscc.validate_package course.imscc --names names.txt

Exit status is 0 when clean, 1 when anything failed. Every check here exists
because the corresponding mistake shipped at least once. See docs/playbook.md
for the stories.

The single most important check is the first one: every .xml in the package
must actually parse. A package whose imsmanifest.xml is not well-formed
imports "successfully" and renders every module item as inert, unclickable
text, because Canvas cannot build a resource map. Regex checks all pass on
such a file. Parse the artifact you are shipping.
"""
import argparse
import html as _html
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

CC = "{http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1}"


def unescape_href(h):
    """Manifest hrefs are XML-escaped; zip entry names are not."""
    return _html.unescape(h)


def check(path, personal_names=()):
    problems, notes = [], []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        # 1. Every XML file must parse. Nothing below means anything if the
        #    manifest is not well-formed.
        for nm in sorted(n for n in names if n.endswith(".xml")):
            try:
                ET.fromstring(z.read(nm))
            except ET.ParseError as exc:
                problems.append("XML is not well-formed: %s -> %s" % (nm, exc))
        if problems:
            return problems, notes          # everything else would be noise

        if "imsmanifest.xml" not in names:
            problems.append("no imsmanifest.xml in the package")
            return problems, notes
        man = z.read("imsmanifest.xml").decode("utf8", "replace")

        # 2. The course_settings resource must be DECLARED, not merely present.
        #    Without this Canvas silently falls back to generic Common
        #    Cartridge: modules look right, but every Assignment imports as a
        #    Page with no points and no gradebook column, the weighted
        #    assignment groups never arrive, and a copy of every page file is
        #    dumped into Files.
        if "course_settings/canvas_export.txt" in names:
            # Look for a RESOURCE whose href is canvas_export.txt, not for the
            # string anywhere in the manifest. The resource also lists
            # canvas_export.txt as one of its own <file> children, so a naive
            # substring test passes even when the resource declaration has been
            # removed. Caught by the smoke test, which is the whole reason it
            # constructs a deliberately broken package.
            resource_blocks = re.findall(r"<resource\b[^>]*>", man)
            declared_settings = any(
                'href="course_settings/canvas_export.txt"' in blk for blk in resource_blocks)
            if not declared_settings:
                problems.append(
                    "course_settings/canvas_export.txt is in the zip but NOT declared as a "
                    "resource in imsmanifest.xml. Canvas will ignore all of course_settings/ "
                    "and every Assignment will import as a Page.")
            else:
                declared = set(re.findall(r'<file href="(course_settings/[^"]+)"', man))
                for f in sorted(n for n in names if n.startswith("course_settings/")):
                    if unescape_href(f) not in {unescape_href(d) for d in declared}:
                        problems.append("course_settings file not listed in its resource: %s" % f)
        else:
            notes.append("no course_settings/ — fine only if this is a content-only package "
                         "with no Assignments, groups or rubrics")

        # 3. Every declared resource file exists as a real zip entry. Checking
        #    the build directory instead of the zip is how a percent-encoding
        #    bug once survived all the way to an import attempt.
        for href in re.findall(r'<file href="([^"]+)"', man):
            if unescape_href(href) not in names:
                problems.append("manifest declares a file that is not in the zip: %s" % href)

        # 4. Every organizations item resolves to a declared resource.
        declared_ids = set(re.findall(r'<resource[^>]*\bidentifier="([^"]+)"', man))
        for ref in re.findall(r'<item[^>]*\bidentifierref="([^"]+)"', man):
            if ref not in declared_ids:
                problems.append("organizations item references undeclared resource: %s" % ref)

        # 5. module_meta agrees with the manifest. ExternalUrl items are the
        #    documented exception: their identifierref points at the
        #    organizations <item> identifier, not at a resource, because the
        #    URL lives in the item itself.
        if "course_settings/module_meta.xml" in names:
            meta = z.read("course_settings/module_meta.xml").decode("utf8", "replace")
            known = declared_ids | set(re.findall(r'<item[^>]*\bidentifier="([^"]+)"', man))
            for ref in re.findall(r"<identifierref>([^<]+)</identifierref>", meta):
                if ref not in known:
                    problems.append("module_meta references undeclared resource: %s" % ref)

            counts = {}
            for ct in re.findall(r"<content_type>([^<]+)</content_type>", meta):
                counts[ct] = counts.get(ct, 0) + 1
            if counts:
                notes.append("module items by type: "
                             + ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())))

        # 6. Assignment group weights sum to 100, or to nothing at all.
        if "course_settings/assignment_groups.xml" in names:
            w = [float(x) for x in re.findall(
                r"<group_weight>([\d.]+)</group_weight>",
                z.read("course_settings/assignment_groups.xml").decode())]
            if w and abs(sum(w) - 100.0) > 0.01:
                problems.append("assignment group weights sum to %s, not 100" % sum(w))

        # 7a. $CANVAS_OBJECT_REFERENCE$ and $CANVAS_COURSE_REFERENCE$ links
        #     must resolve to something in the package. These are Canvas's
        #     placeholders for "a module in this course" and "a file in this
        #     course". A stale one is what Canvas reports on import as
        #     "Missing links found in imported content - Wiki Page body", and
        #     they survive being copied from course to course for years.
        ids = set(re.findall(r'identifier(?:ref)?="([^"]+)"', man))
        if "course_settings/module_meta.xml" in names:
            ids |= set(re.findall(r"<identifierref>([^<]+)</identifierref>",
                                  z.read("course_settings/module_meta.xml").decode("utf8", "replace")))
        for nm in sorted(n for n in names if n.endswith(".html")):
            body = z.read(nm).decode("utf8", "replace")
            for ref in re.findall(
                    r"\$CANVAS_(?:OBJECT|COURSE)_REFERENCE\$/(?:modules|file_ref)/([a-z0-9]+)",
                    body):
                if ref not in ids:
                    problems.append("dangling Canvas reference in %s -> %s" % (nm, ref))

        # 7. No dangling $IMS-CC-FILEBASE$ links. These are relative to
        #    web_resources/ and are percent-encoded and then XML-escaped, and
        #    Canvas's encoding is not urllib's (it leaves commas literal), so
        #    compare after decoding both sides.
        import urllib.parse
        web = {n[len("web_resources/"):] for n in names if n.startswith("web_resources/")}
        for nm in sorted(n for n in names if n.endswith(".html")):
            body = z.read(nm).decode("utf8", "replace")
            for tgt in re.findall(r"\$IMS-CC-FILEBASE\$/([^\"'?#\s>]+)", body):
                clean = urllib.parse.unquote(_html.unescape(tgt))
                if clean not in web:
                    problems.append("dangling file link in %s -> %s" % (nm, clean))

        # 8. Assignments, if any, must reference a declared group.
        groups = set(re.findall(r'<assignmentGroup identifier="([^"]+)"',
                                z.read("course_settings/assignment_groups.xml").decode())
                     ) if "course_settings/assignment_groups.xml" in names else set()
        n_assign = 0
        for nm in sorted(n for n in names if n.endswith("/assignment_settings.xml")):
            n_assign += 1
            s = z.read(nm).decode("utf8", "replace")
            g = re.search(r"<assignment_group_identifierref>([^<]+)<", s)
            if g and groups and g.group(1) not in groups:
                problems.append("assignment %s references an undeclared group" % nm)
        if n_assign:
            notes.append("%d assignment(s)" % n_assign)

        # 9. Personal data. Sweep zip ENTRY NAMES as well as file contents:
        #    a student's name can survive inside an <img alt> long after the
        #    file itself was renamed, because Canvas copies the original
        #    filename into the alt text.
        for person in personal_names:
            for nm in sorted(names):
                if person.lower() in nm.lower():
                    problems.append("name %r appears in a filename: %s" % (person, nm))
                if nm.endswith((".xml", ".html", ".txt")):
                    if person.lower() in z.read(nm).decode("utf8", "replace").lower():
                        problems.append("name %r appears inside %s" % (person, nm))

        # 10. Empty directory entries. A zip records folders separately, so a
        #     folder whose files all moved away is still listed and Canvas
        #     still shows it.
        for d in sorted(n for n in names if n.endswith("/")):
            if not any(n != d and n.startswith(d) for n in names):
                problems.append("empty directory entry left in the zip: %s" % d)

        notes.append("%d entries, %s bytes" % (len(names), format(
            sum(i.file_size for i in z.infolist()), ",d")))
    return problems, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("package")
    ap.add_argument("--names", help="file of names, one per line, that must NOT appear "
                                    "anywhere in the package (students, model bookings)")
    a = ap.parse_args()
    people = []
    if a.names:
        people = [ln.strip() for ln in open(a.names) if ln.strip()]
    problems, notes = check(a.package, people)
    for n in notes:
        print("  " + n)
    if problems:
        print("\nVALIDATION FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nvalidation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
