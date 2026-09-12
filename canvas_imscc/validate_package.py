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

Accessibility is checked separately, by canvas_imscc.accessibility, and is
summarised here as a note. It does NOT affect exit status unless you pass
--a11y-strict, because a missing alt attribute is not a reason to block a
build, and a validator that cries wolf gets switched off. Pass --a11y for the
full report.

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


CCX = "{http://canvas.instructure.com/xsd/cccv1p0}"


def _carries_links(name):
    """Entries whose body can contain $IMS-CC-FILEBASE$ or $CANVAS_*$ links.

    Not just .html. A discussion or announcement stores its body as escaped
    HTML inside <text> in its own .xml at the package root, and assignment
    settings can carry links too. Scanning only .html means dangling links in
    every announcement are invisible; a package once shipped with seven of
    them and validated clean.
    """
    if name.startswith("web_resources/") or name.endswith("/"):
        return False
    return name.endswith((".html", ".xml", ".txt"))


def _link_text(name, data):
    """The text of an entry, with any embedded escaped HTML decoded first.

    A discussion or announcement stores its body as HTML *escaped inside XML*:
    <text texttype="text/html">&lt;a href="...A&amp;amp;D.pdf"&gt;</text>.
    That is two layers, so scanning the raw bytes and unescaping a matched
    link once leaves "A&amp;D" and reports a dangling link for a file that is
    present. Decode the wrapper first, then the usual single unescape of each
    matched reference is correct.
    """
    if name.endswith(".xml") and 'texttype="text/html"' in data:
        return _html.unescape(data)
    return data


def unescape_href(h):
    """Manifest hrefs are XML-escaped; zip entry names are not."""
    return _html.unescape(h)


def check(path, personal_names=(), a11y=True):
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
                # Which course_settings files are listed is a NOTE, not a
                # failure. Real Canvas exports ship files here that the
                # resource does not list (media_tracks.xml is the common one),
                # and they import fine, because Canvas reads the directory
                # once it has decided the package is Canvas-flavored. Only the
                # canvas_export.txt declaration above decides that. Skip the
                # bare "course_settings/" directory entry, which is not a file
                # and was reported as one against every real export tested.
                declared = {unescape_href(d) for d in re.findall(
                    r'<file href="(course_settings/[^"]+)"', man)}
                undeclared = [f for f in sorted(names)
                              if f.startswith("course_settings/")
                              and not f.endswith("/")
                              and unescape_href(f) not in declared]
                if undeclared:
                    notes.append("course_settings files not listed in the resource: %s "
                                 "(normal in real exports; Canvas reads the directory)"
                                 % ", ".join(undeclared))
        else:
            notes.append("no course_settings/ — fine only if this is a content-only package "
                         "with no Assignments, groups or rubrics")

        # 3. Every declared resource file exists as a real zip entry. Checking
        #    the build directory instead of the zip is how a percent-encoding
        #    bug once survived all the way to an import attempt.
        for href in re.findall(r'<file href="([^"]+)"', man):
            if unescape_href(href) not in names:
                problems.append("manifest declares a file that is not in the zip: %s" % href)

        # 3b. And the other direction: every file IN the zip is declared by
        #     some resource. Check 3 asks "does every declared file exist",
        #     which passes clean on a package carrying files nobody declared.
        #     That is not academic. add_page_resource() renames rather than
        #     overwrites when a file is already in the build directory, so a
        #     second build into a dirty directory leaves aquatint-2.html
        #     beside aquatint.html; the manifest points only at the new one,
        #     but zip_package() zips the whole folder. A package once shipped
        #     193 entries where 79 were declared, and every check passed. On
        #     import those orphans land in Files as content nobody asked for.
        #
        #     course_settings/ is exempt because check 2 owns it and real
        #     exports legitimately ship undeclared files there. Directory
        #     entries are check 10's business.
        #
        #     Only a hard failure for Canvas-flavored packages, which are the
        #     ones this kit builds and mutates. A generic Common Cartridge
        #     from another LMS may carry a whole undeclared static-site tree
        #     by design, and failing those would be answering a question
        #     nobody asked. Measured against a corpus of real exports from
        #     five LMSes: zero false positives on the Canvas ones.
        declared_files = {unescape_href(h) for h in re.findall(r'<file href="([^"]+)"', man)}
        declared_files |= {unescape_href(h) for h in
                           re.findall(r'<resource\b[^>]*\bhref="([^"]+)"', man)}
        declared_files.add("imsmanifest.xml")
        orphans = [n for n in sorted(names)
                   if not n.endswith("/")
                   and not n.startswith("course_settings/")
                   and unescape_href(n) not in declared_files]
        if orphans:
            where = (problems if "course_settings/canvas_export.txt" in names else notes)
            head = ("%d file(s) are in the zip but declared by no resource, so Canvas "
                    "imports them into Files as content nobody asked for:" % len(orphans))
            where.append(head + "".join("\n      " + o for o in orphans[:20])
                         + ("\n      ... and %d more" % (len(orphans) - 20)
                            if len(orphans) > 20 else ""))

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

            # 5b. Every module and module ITEM in module_meta must also
            #     appear in <organizations>. Canvas builds the module tree
            #     from <organizations>; module_meta only decorates it with
            #     workflow_state, content_type and indent. A module or item
            #     added to module_meta alone is not malformed and not
            #     dangling, it simply does not exist after import, silently.
            #     A whole module of assignments has gone missing this way.
            org_item_ids = set(re.findall(
                r'<item[^>]*\bidentifier="([^"]+)"', man))
            meta_root = None
            try:
                meta_root = ET.fromstring(meta)
            except ET.ParseError:
                pass                       # check 1 already reported this
            if meta_root is not None:
                for mod in meta_root:
                    mod_title = mod.findtext("%stitle" % CCX) or "?"
                    if mod.get("identifier") not in org_item_ids:
                        problems.append(
                            "module %r is in module_meta but NOT in "
                            "<organizations>, so it will not import"
                            % mod_title)
                    holder = mod.find("%sitems" % CCX)
                    for it in (holder if holder is not None else []):
                        if it.get("identifier") not in org_item_ids:
                            problems.append(
                                "module item %r (in %r) is in module_meta but "
                                "NOT in <organizations>, so it will not import"
                                % (it.findtext("%stitle" % CCX) or "?",
                                   mod_title))

            # 5c. An ExternalUrl item whose <url> is missing or empty. Canvas
            #     has nothing to link to, so it drops the item on import: no
            #     error, no placeholder, the link is just not there. The
            #     cartridge viewer shows a dead entry. Found 2026-09-10 on a
            #     package built by this kit, which accepted 'ExternalUrl' as a
            #     content_type and had no way to carry a url at all.
            if meta_root is not None:
                org_refs = dict(re.findall(
                    r'<item[^>]*\bidentifier="([^"]+)"[^>]*\bidentifierref="([^"]+)"',
                    man))
                weblinks = set(re.findall(
                    r'<resource identifier="([^"]+)" type="imswl_xmlv1p1"', man))
                for mod in meta_root:
                    holder = mod.find("%sitems" % CCX)
                    for it in (holder if holder is not None else []):
                        if it.findtext("%scontent_type" % CCX) != "ExternalUrl":
                            continue
                        title = it.findtext("%stitle" % CCX) or "?"
                        if not (it.findtext("%surl" % CCX) or "").strip():
                            problems.append(
                                "external link %r has no <url> in module_meta, "
                                "so Canvas drops the item on import without "
                                "saying anything" % title)
                        if org_refs.get(it.get("identifier")) not in weblinks:
                            notes.append(
                                "external link %r has no imswl_xmlv1p1 weblink "
                                "resource, so it is invisible to the cartridge "
                                "viewer and to non-Canvas LMSes (Canvas itself "
                                "reads the <url> and is unaffected)" % title)

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
            # All-zero weights mean the course does not use weighted groups
            # at all: the gradebook is straight points. That is a normal,
            # correct setup and a real Canvas export of such a course looks
            # exactly like this, so flagging it cried wolf on valid packages.
            #
            # And weights are INERT unless course_settings.xml says
            # <group_weighting_scheme>percent</group_weighting_scheme>. A
            # package can carry a perfect set of weights and still grade on
            # straight points, silently, which is its own bug (see below).
            # Enforcing the sum on a course that is not weighted at all fails
            # real, correct exports.
            scheme = ""
            if "course_settings/course_settings.xml" in names:
                m = re.search(r"<group_weighting_scheme>([^<]*)<",
                              z.read("course_settings/course_settings.xml").decode(
                                  "utf8", "replace"))
                scheme = m.group(1).strip() if m else ""
            #
            # Weights that sum to 100 with the scheme off is the trap: someone
            # meant to weight the gradebook and the package silently will not.
            # Weights that do NOT sum to 100 with the scheme off are just
            # leftovers, because Canvas keeps whatever was typed in the group
            # fields after weighting is switched back off, and a real export
            # of a healthy points-based course looks exactly like that.
            if any(w) and scheme != "percent":
                if abs(sum(w) - 100.0) <= 0.01:
                    problems.append(
                        "assignment group weights sum to 100 but course_settings.xml does not "
                        "set <group_weighting_scheme>percent</group_weighting_scheme>, so "
                        "Canvas imports the weights and grades on straight points anyway. "
                        "Every grade in the course will be wrong and nothing will say so.")
                else:
                    notes.append("assignment groups carry stale weights (%s) that sum to %g, "
                                 "but the course is not weighted, so they are inert"
                                 % (", ".join("%g" % x for x in w), sum(w)))
            elif any(w) and abs(sum(w) - 100.0) > 0.01:
                problems.append("assignment group weights sum to %s, not 100, and the course "
                                "is set to weight by percent" % sum(w))
            elif w and not any(w):
                notes.append("assignment groups are unweighted (points-based "
                             "gradebook)")

        # 6b. Rubrics have to add up. Canvas imports a rubric whose criteria do
        #     not sum to its points_possible without a word of complaint, and
        #     the arithmetic is not visible anywhere until someone grades with
        #     it. Two ways a mutation produces one:
        #
        #     A criterion SILENTLY DROPPED. Rewriting a rubric's criteria in
        #     place, by zipping a new list against the elements already there,
        #     ignores anything past the end of the old list. Going from three
        #     criteria to four left a 100-point assignment carrying an 80-point
        #     rubric, and nothing anywhere said so.
        #
        #     A RATING SCALE left on the old numbers. Rescaling each rating by
        #     old/oldmax*new after already writing the new value into the
        #     criterion makes oldmax equal to new, so every rating divides by
        #     itself and keeps last year's points. A 30-point criterion still
        #     topped out at a 40-point "Excellent".
        #
        #     Both survived a full build, the package's own checks and a
        #     cartridge-viewer pass, because nothing else in a package reads
        #     these numbers.
        if "course_settings/rubrics.xml" in names:
            try:
                rroot = ET.fromstring(z.read("course_settings/rubrics.xml"))
            except ET.ParseError:
                rroot = None
            for rub in rroot if rroot is not None else ():
                title = rub.findtext(CCX + "title") or "?"
                try:
                    pp = float(rub.findtext(CCX + "points_possible") or 0)
                except ValueError:
                    pp = 0.0
                crits = rub.findall(".//" + CCX + "criterion")
                if not crits:
                    problems.append("rubric %r has no criteria" % title)
                    continue
                total = 0.0
                for c in crits:
                    try:
                        cp = float(c.findtext(CCX + "points") or 0)
                    except ValueError:
                        cp = 0.0
                    total += cp
                    tops = []
                    for rat in c.findall(CCX + "ratings"):
                        for r in rat:
                            try:
                                tops.append(float(r.findtext(CCX + "points") or 0))
                            except ValueError:
                                pass
                    if tops and cp and abs(max(tops) - cp) > 0.001:
                        problems.append(
                            "rubric %r criterion %r tops out at %g but the criterion is "
                            "worth %g" % (title, c.findtext(CCX + "description"),
                                          max(tops), cp))
                if pp and abs(total - pp) > 0.001:
                    problems.append(
                        "rubric %r criteria sum to %g but points_possible is %g"
                        % (title, total, pp))

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
        for nm in sorted(n for n in names if _carries_links(n)):
            body = _link_text(nm, z.read(nm).decode("utf8", "replace"))
            for ref in re.findall(
                    r"\$CANVAS_(?:OBJECT|COURSE)_REFERENCE\$/(?:modules|file_ref)/([a-z0-9]+)",
                    body):
                if ref not in ids:
                    problems.append("dangling Canvas reference in %s -> %s" % (nm, ref))

        # 7b. $WIKI_REFERENCE$ page links must use the one form Canvas
        #     resolves. This is cheap and it would have caught 54 broken links
        #     in a package that passed every other check, passed the cartridge
        #     viewer, and passed a bespoke check confirming every target
        #     matched a real page's slug. Nothing catches it until import, and
        #     import reports it only as "Missing links found in imported
        #     content - Wiki Page body".
        #
        #       /pages/<resource id>                   correct
        #       /pages/<id>#anchor                     BREAKS: Canvas absorbs
        #                                              the fragment into the
        #                                              identifier and offers to
        #                                              create the missing page
        #       /pages/<id>?titleize=0#anchor          correct, and jumps
        #       /wiki_pages/<anything>                 never resolves
        #
        #     canvas-lms parses the object id with UriMatch#query = rest[/\?.*/],
        #     so "?" is what terminates it. All confirmed by live import.
        for nm in sorted(n for n in names if _carries_links(n)):
            body = _link_text(nm, z.read(nm).decode("utf8", "replace"))
            for wref in re.findall(r"\$WIKI_REFERENCE\$(/[^\"'\s>]*)", body):
                seg = wref.split("/", 2)
                kind = seg[1] if len(seg) > 1 else ""
                if kind not in ("pages", "wiki"):
                    problems.append(
                        "%s links to $WIKI_REFERENCE$%s. Canvas resolves "
                        "/pages/<resource id>; %r is not a route it serves"
                        % (nm, wref, "/" + kind))
                    continue
                rest = seg[2] if len(seg) > 2 else ""
                if "#" in rest and "?" not in rest.split("#", 1)[0]:
                    problems.append(
                        "%s links to $WIKI_REFERENCE$%s. A fragment needs a query "
                        "string in front of it or Canvas reads the anchor as part "
                        "of the page id and the link breaks. Use "
                        "?titleize=0#<anchor>" % (nm, wref))
                    continue
                target = rest.split("?")[0].split("#")[0]
                # A slug target is legal; only an id target can be checked.
                if kind == "pages" and re.fullmatch(r"g[0-9a-f]{32}", target) \
                        and target not in ids:
                    problems.append(
                        "%s links to $WIKI_REFERENCE$%s, and %s is not a resource "
                        "declared in this package" % (nm, wref, target))

        # 7. No dangling $IMS-CC-FILEBASE$ links. These are relative to
        #    web_resources/ and are percent-encoded and then XML-escaped, and
        #    Canvas's encoding is not urllib's (it leaves commas literal), so
        #    compare after decoding both sides.
        import urllib.parse
        web = {n[len("web_resources/"):] for n in names if n.startswith("web_resources/")}
        for nm in sorted(n for n in names if _carries_links(n)):
            body = _link_text(nm, z.read(nm).decode("utf8", "replace"))
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
            # Say how many are ALSO module items. module_meta.xml records
            # module membership and nothing else, so an assignment that is not
            # in any module contributes no <content_type>Assignment</> line
            # while being a perfectly healthy assignment with a gradebook
            # column. Reading a zero there as "they all imported as Pages" is a
            # mistake this note exists to prevent; it has been made.
            in_modules = 0
            if "course_settings/module_meta.xml" in names:
                meta_txt = z.read("course_settings/module_meta.xml").decode(
                    "utf8", "replace")
                in_modules = meta_txt.count(
                    "<content_type>Assignment</content_type>")
            if in_modules == n_assign:
                notes.append("%d assignment(s), all placed in a module"
                             % n_assign)
            else:
                notes.append(
                    "%d assignment(s), %d placed in a module. The other %d "
                    "exist and are gradeable, they are just not linked from "
                    "any module -- that is normal, NOT evidence they imported "
                    "as Pages" % (n_assign, in_modules, n_assign - in_modules))

        # 8b. Rubric associations. "Use this rubric for grading" lives on the
        #     ASSOCIATION between a rubric and an assignment, not on the rubric,
        #     so it only ships when the two travel together. A rubrics-only
        #     package carries no association at all and every rubric has to be
        #     attached and ticked by hand in Canvas. Report it either way, so
        #     the question "is it already ticked?" is answerable without
        #     unzipping anything.
        attached = graded = 0
        for nm in sorted(n for n in names if n.endswith("/assignment_settings.xml")):
            txt = z.read(nm).decode("utf8", "replace")
            if "<rubric_identifierref>" in txt:
                attached += 1
                if re.search(r"<rubric_use_for_grading>\s*true\s*<", txt):
                    graded += 1
        if attached:
            notes.append(
                "%d of %d assignment(s) ship with a rubric attached, %d of "
                "those set to 'use this rubric for grading'"
                % (attached, n_assign, graded))
        elif "course_settings/rubrics.xml" in names:
            notes.append(
                "rubrics ship with NO assignment association, so each one has "
                "to be attached by hand in Canvas and 'use this rubric for "
                "grading' ticked by hand. That is inherent to a rubrics-only "
                "package, not a defect")

        # 8c. Published state, reported rather than judged: only the instructor
        #     knows whether this package is meant to go live on import. It is
        #     worth seeing BEFORE importing into a course students can see.
        #     Canvas's spellings differ by object: pages, modules and module
        #     items use active/unpublished, assignments use published/
        #     unpublished.
        pub_bits = []
        n_unpub_pages = sum(
            1 for nm in names if nm.startswith("wiki_content/") and nm.endswith(".html")
            and 'name="workflow_state" content="unpublished"' in
                z.read(nm).decode("utf8", "replace"))
        n_pages_total = sum(1 for nm in names
                            if nm.startswith("wiki_content/") and nm.endswith(".html"))
        if n_pages_total:
            pub_bits.append("%d/%d page(s) unpublished" % (n_unpub_pages, n_pages_total))
        if n_assign:
            n_unpub_a = sum(
                1 for nm in names if nm.endswith("/assignment_settings.xml")
                and "<workflow_state>unpublished</workflow_state>" in
                    z.read(nm).decode("utf8", "replace"))
            pub_bits.append("%d/%d assignment(s) unpublished" % (n_unpub_a, n_assign))
        if "course_settings/module_meta.xml" in names and meta_root is not None:
            mods_unpub = sum(1 for m in meta_root
                             if m.findtext("%sworkflow_state" % CCX) == "unpublished")
            n_mods = len(list(meta_root))
            if n_mods:
                pub_bits.append("%d/%d module(s) unpublished" % (mods_unpub, n_mods))
            # The one combination that never appears in a real export: an item
            # more published than the thing it points at.
            page_state = {}
            for rid, h in re.findall(
                    r'<resource identifier="([^"]+)"[^>]*href="(wiki_content/[^"]+)"', man):
                h = unescape_href(h)
                if h in names:
                    page_state[rid] = (
                        "unpublished" if 'content="unpublished"' in
                        z.read(h).decode("utf8", "replace") else "active")
            for mod in meta_root:
                holder = mod.find("%sitems" % CCX)
                for it in (holder if holder is not None else []):
                    ref = it.findtext("%sidentifierref" % CCX)
                    if (it.findtext("%sworkflow_state" % CCX) == "active"
                            and page_state.get(ref) == "unpublished"):
                        problems.append(
                            "module item %r is published but the page it points "
                            "at is not. Canvas has no such state in any real "
                            "export; the item will not show"
                            % (it.findtext("%stitle" % CCX) or "?"))
        if pub_bits:
            notes.append("published state: " + ", ".join(pub_bits))

        # 8d. Quizzes. A Canvas export writes each quiz twice: an empty CC
        #     shell at <rid>/assessment_qti.xml and the real questions at
        #     non_cc_assessments/<rid>.xml.qti. Ship only the shell and Canvas
        #     imports a quiz with no questions and says nothing, which is the
        #     single easiest way to get this format wrong.
        quiz_ids = re.findall(
            r'<resource identifier="([^"]+)" type="imsqti_xmlv1p2/imscc_xmlv1p1/assessment"', man)
        n_questions = 0
        empty = []
        for qid in quiz_ids:
            cc_name = "%s/assessment_qti.xml" % qid
            nc_name = "non_cc_assessments/%s.xml.qti" % qid
            title = qid
            if cc_name in names:
                cc = z.read(cc_name).decode("utf8", "replace")
                m = re.search(r'<assessment[^>]*title="([^"]*)"', cc)
                if m:
                    title = m.group(1)
                cc_items = cc.count("<item ")
            else:
                cc_items = 0
                problems.append("quiz %s declares %s but it is not in the package"
                                % (title, cc_name))
            if nc_name in names:
                nc = z.read(nc_name).decode("utf8", "replace")
                nc_items = nc.count("<item ")
                n_questions += nc_items
                if nc_items == 0 and cc_items == 0:
                    # A NOTE, not a failure. Instructure's own summer template
                    # ships 11 quizzes exactly like this: deliberate empty
                    # shells for the instructor to fill, with the questions in
                    # separate question-bank files. Failing that export would
                    # be failing correct work.
                    empty.append(title)
            elif cc_items:
                notes.append(
                    "quiz %r keeps its questions in the CC assessment_qti.xml "
                    "and ships no non_cc_assessments file. Canvas's own exports "
                    "do the opposite; this may still import, but it is not the "
                    "shape Canvas produces" % title)
                n_questions += cc_items
            else:
                empty.append(title)

            meta_name = "%s/assessment_meta.xml" % qid
            if meta_name not in names:
                problems.append("quiz %r has no assessment_meta.xml, so it has "
                                "no title, points or settings" % title)
            else:
                meta = z.read(meta_name).decode("utf8", "replace")
                qt = re.search(r"<quiz_type>([^<]+)</quiz_type>", meta)
                qt = qt.group(1) if qt else "?"
                if (qt in ("assignment", "graded_survey")
                        and "<assignment_group_identifierref>" not in meta):
                    notes.append(
                        "quiz %r is graded (%s) but names no assignment group, "
                        "so Canvas picks one and any weighted gradebook is "
                        "wrong" % (title, qt))
        if quiz_ids:
            notes.append("%d quiz/quizzes carrying %d question(s)"
                         % (len(quiz_ids), n_questions))
            if empty:
                notes.append(
                    "%d quiz/quizzes have NO questions and will import empty: "
                    "%s. Deliberate in a template course, a bug anywhere else, "
                    "so this is reported and not failed"
                    % (len(empty), ", ".join(repr(t) for t in empty[:4])
                       + (" ..." if len(empty) > 4 else "")))
            banks = [n for n in names
                     if n.startswith("non_cc_assessments/")
                     and n.endswith(".xml.qti")
                     and n[len("non_cc_assessments/"):-len(".xml.qti")] not in quiz_ids]
            if banks:
                total = sum(z.read(n).decode("utf8", "replace").count("<item ")
                            for n in banks)
                notes.append(
                    "%d non_cc_assessments file(s) carrying %d question(s) belong "
                    "to no declared quiz: almost certainly QUESTION BANKS, which "
                    "this kit does not build and cannot check"
                    % (len(banks), total))

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
        #     Only under web_resources/ though: that is the tree Canvas turns
        #     into the course's Files, so an empty one shows up as an empty
        #     folder a student can click. Everywhere else an empty directory
        #     entry is cosmetic, and Canvas's own exports ship them
        #     (non_cc_assessments/ in a real single-page export), so failing on
        #     those failed real packages for no reason.
        for d in sorted(n for n in names if n.endswith("/")):
            if not any(n != d and n.startswith(d) for n in names):
                if d.startswith("web_resources/"):
                    problems.append("empty Files folder left in the zip: %s" % d)
                else:
                    notes.append("empty directory entry in the zip (cosmetic): %s" % d)

        # WHEN this package was made, which is not a nicety. Exports pile up
        # in a folder and they all look alike; reasoning about an old one
        # produces confident, wrong conclusions about the live course. A real
        # case: a course was declared broken (assignments missing, rubrics
        # gone) from an export that predated the import that added them.
        # Canvas puts no date inside the package -- canvas_export.txt is a
        # joke file, literally -- so the zip entry timestamps are the record.
        stamps = [i.date_time for i in z.infolist() if i.date_time[0] > 1980]
        if stamps:
            notes.append("package built %04d-%02d-%02d %02d:%02d "
                         "(newest entry timestamp -- check this is the export "
                         "you think it is)" % max(stamps)[:5])

        notes.append("%d entries, %s bytes" % (len(names), format(
            sum(i.file_size for i in z.infolist()), ",d")))

    # 11. Accessibility, summarised but never enforced, and deliberately kept
    #     out of `problems`. These do not stop the package importing; they stop
    #     some students using it. Mixing the two teaches people to ignore both.
    #     HTML only here, because scanning PDFs means reading every byte of an
    #     export that is mostly PDFs. `--a11y` does the full pass.
    #
    #     This function still returns a 2-tuple. Anything already calling
    #     check() keeps working.
    if a11y:
        from .accessibility import audit_package
        findings, a_counts = audit_package(path, skip_pdfs=True)
        pages = a_counts["html"] + a_counts["xml_bodies"]
        n_err = sum(1 for f in findings if f.severity == "error")
        if findings:
            notes.append(
                "accessibility: %d error(s), %d warning(s) across %d html "
                "page(s), pdfs not scanned — run `python3 -m "
                "canvas_imscc.accessibility <package> --a11y` for detail"
                % (n_err, len(findings) - n_err, pages))
        else:
            notes.append("accessibility: no automated problems in %d html "
                         "page(s) (pdfs not scanned)" % pages)
    # 12. Possible student data, reported and never enforced, for the same
    #     reason as the accessibility notes: this cannot decide anything, it
    #     can only tell a human where to look. See canvas_imscc/privacy.py.
    if a11y:
        from .privacy import audit_privacy
        pf, _ = audit_privacy(path)
        if pf:
            n_rev = sum(1 for f in pf if f.severity == "review")
            notes.append(
                "possible student data: %d to review, %d to look at — run "
                "`python3 -m canvas_imscc.privacy <package>`. Not a "
                "compliance check; nothing here blocks anything"
                % (n_rev, len(pf) - n_rev))

    return problems, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("package")
    ap.add_argument("--names", help="file of names, one per line, that must NOT appear "
                                    "anywhere in the package (students, model bookings)")
    ap.add_argument("--a11y", action="store_true",
                    help="print the full accessibility report, including PDFs")
    ap.add_argument("--a11y-strict", action="store_true",
                    help="also fail (exit 1) on accessibility errors")
    a = ap.parse_args()
    people = []
    if a.names:
        people = [ln.strip() for ln in open(a.names) if ln.strip()]
    want_a11y = a.a11y or a.a11y_strict
    # When the full report is coming, skip the summary so the audit runs once.
    problems, notes = check(a.package, people, a11y=not want_a11y)
    for n in notes:
        print("  " + n)
    findings = []
    if want_a11y:
        from .accessibility import audit_package, format_report
        findings, a_counts = audit_package(a.package)
        print("\n--- accessibility ---")
        print(format_report(findings, a_counts))
    failed = bool(problems)
    if problems:
        print("\nVALIDATION FAILED")
        for p in problems:
            print("  - " + p)
    if a.a11y_strict and any(f.severity == "error" for f in findings):
        print("\nACCESSIBILITY ERRORS (--a11y-strict)")
        failed = True
    if failed:
        return 1
    print("\nvalidation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
