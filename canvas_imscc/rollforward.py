#!/usr/bin/env python3
"""Helpers for rolling a course forward by MUTATING a real Canvas export.

When the next offering of a course is mostly the previous offering, do not
rebuild it with builder.py. Take the Canvas export of the previous term and
change only what has to change.

A genuine export already satisfies every structural requirement in
docs/playbook.md, including the course_settings manifest declaration that
everything else hinges on, and it carries the assignments, rubrics, groups,
grading standard, files and presentations through untouched at zero effort
and zero risk. Rebuilding those from scratch is work you do not need to do
and risk you do not need to take.

The pattern: stream the source .imscc entry by entry, classify each one as
drop / replace / copy, then append new entries. A multi-gigabyte package is
transformed without ever being unpacked. See docs/mutating-an-export.md for
the full walkthrough and examples.

Every function here exists because of a specific bug. The comments say which.
"""
import copy
import datetime
import html as _html
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile


# ---------------------------------------------------------------------------
# Paths: the same file is spelled three different ways in one package
# ---------------------------------------------------------------------------
# Characters Canvas leaves LITERAL when it percent-encodes a path behind
# $IMS-CC-FILEBASE$. Taken from real exports, not from a standard: a colon is
# the one most likely to bite, because urllib encodes it as %3A by default but
# Canvas writes "Project 1: Notes/x.gif" as "Project%201:%20Notes/x.gif".
CANVAS_SAFE = "/:,()!$&+'"


def path_spellings(path):
    """Every spelling of one path that might appear anywhere in a package.

    imsmanifest.xml XML-escapes hrefs ("Presentations &amp; PDFs", and a quote
    as &quot;). Page HTML percent-encodes them behind $IMS-CC-FILEBASE$ and
    then XML-escapes that. And Canvas does not percent-encode the way urllib
    does by default: it leaves commas, colons and several other characters
    literal, so "Dec 15, 2021" comes out "Dec%2015,%202021", not
    "Dec%2015%2C%202021".

    Sorted longest first, so a plain spelling can never eat part of an
    escaped one.

    PREFER remap_references() over building your own matcher on top of this.
    Generating candidate spellings can only ever cover the encodings someone
    thought of; decoding what is actually in the file cannot miss one.
    """
    out = set()
    for v in (path,
              urllib.parse.quote(path, safe="/"),
              urllib.parse.quote(path, safe=CANVAS_SAFE)):
        out.add(v)
        # quote=False leaves a literal " alone. A manifest href CANNOT: it
        # writes &quot;, or the attribute would end early and the XML would be
        # malformed. A real export contains
        #   href="web_resources/Rikard &quot;Color Harmony...&quot; (2015).pdf"
        # and omitting this spelling meant such files were never rewritten.
        out.add(_html.escape(v, quote=False))
        out.add(_html.escape(v, quote=True))
    return sorted(out, key=len, reverse=True)


def xml_href(path):
    """A path as it must be written inside an XML attribute.

    The double quote MUST be escaped. A filename containing one is not exotic
    (an article title in quotation marks, saved as a PDF, produces one), and
    leaving it literal ends the attribute early and makes imsmanifest.xml
    malformed, which imports "successfully" and renders every module item as
    inert, unclickable text.

    The apostrophe is deliberately left literal: real Canvas exports contain
    &quot; and &amp; but never &#x27;, and html.escape(quote=True) would emit
    it, so output would stop matching what Canvas itself writes.
    """
    return (path.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def html_href(path):
    """A path as it must be written behind $IMS-CC-FILEBASE$ in page HTML."""
    return _html.escape(urllib.parse.quote(path, safe=CANVAS_SAFE), quote=False)


_FILEBASE_RE = re.compile(r"(\$IMS-CC-FILEBASE\$/)([^\"'?#\s>]+)")
_ATTR_RE = re.compile(r'((?:href|src)=")([^"]+)(")')


def remap_references(text, remap, mode, prefix="web_resources/"):
    """Rewrite references to moved files by DECODING them, not by guessing.

    Same job as apply_remap, but instead of generating candidate spellings of
    each old path and hoping one appears, it finds every reference the format
    can contain, decodes it to a plain path, looks that up, and re-emits it in
    the encoding this format requires. A spelling nobody anticipated is still
    matched, because it is decoded rather than compared. A reference to a path
    that is not being moved is left exactly as it was.

    mode is "xml" for the manifest and settings files, "html" for page bodies.
    """
    emit = xml_href if mode == "xml" else html_href

    def fix_filebase(m):
        head, ref = m.group(1), m.group(2)
        rel = urllib.parse.unquote(_html.unescape(ref))
        return head + html_href(remap[rel]) if rel in remap else m.group(0)

    def fix_attr(m):
        head, ref, tail = m.groups()
        plain = _html.unescape(ref)
        for candidate in (plain, urllib.parse.unquote(plain)):
            if candidate.startswith(prefix) and candidate[len(prefix):] in remap:
                return head + emit(prefix + remap[candidate[len(prefix):]]) + tail
        return m.group(0)

    text = _FILEBASE_RE.sub(fix_filebase, text)
    return _ATTR_RE.sub(fix_attr, text)


def apply_remap(text, remap, mode):
    """Rewrite every spelling of each old path to ONE correctly encoded new one.

    Consider remap_references() instead: it decodes each reference rather than
    generating candidate spellings, so it cannot miss an encoding. This
    function is kept because it also rewrites bare path mentions outside of an
    attribute, which the parsing version deliberately leaves alone.

    mode is "xml" for manifest/settings files, "html" for page bodies.

    Matching many spellings and EMITTING many spellings, pairwise, is the bug
    this function exists to prevent. Pairing plain-old with plain-new and
    escaped-old with escaped-new is wrong the moment the two paths need
    different escaping: moving "unfiled/x.pdf" to "Syllabi & Schedules/x.pdf"
    wrote a bare & into an href, which made imsmanifest.xml invalid XML, which
    made every module item in the imported course render as inert, unclickable
    text. So: match anything, but always emit the encoding the destination
    format requires.
    """
    emit = xml_href if mode == "xml" else html_href
    for old, new in remap.items():
        target = emit(new)
        for spelling in path_spellings(old):
            text = text.replace(spelling, target)
    return text


def assert_paths_exist(zip_names, *maps):
    """Fail loudly if a path in a rename/drop map is not in the package.

    Filenames contain characters that look ordinary and are not. A macOS
    screenshot stored as "8.55.41 PM.png" used a NARROW NO-BREAK SPACE
    (U+202F); a remap keyed on a normal space matched nothing and failed in
    silence. Discovering that downstream costs far more than failing here.
    """
    missing = [p for m in maps for p in m if p not in zip_names]
    if missing:
        raise SystemExit("paths in a remap are not in the package: %r" % missing)


# ---------------------------------------------------------------------------
# Due dates
# ---------------------------------------------------------------------------
def due_fields(datestr, clock=None, utc_offset=None):
    """(due_at, all_day_date, all_day) for a local due date, Canvas's way.

    due_at is UTC; all_day_date is the LOCAL date. An all-day assignment due
    at 11:59pm local is written at hour (offset - 1) on the FOLLOWING UTC day:
    2026-02-19 at UTC-5 becomes 2026-02-20T04:59:59, and 2026-03-12 at UTC-4
    becomes 2026-03-13T03:59:59. Getting this off by one is easy and
    invisible.

    datestr is "YYYY-MM-DD". clock is "HH:MM" local for a timed deadline, or
    None for the 11:59pm all-day default. utc_offset is hours WEST of UTC
    (5 for US Eastern standard time, 4 for daylight) and must be supplied by
    the caller, because only the caller knows the course's timezone and where
    its daylight-saving boundaries fall.

    Cheap way to confirm you have it right: leave one assignment's date
    untouched and compare your output against what Canvas itself wrote.
    """
    if utc_offset is None:
        raise ValueError("utc_offset is required: pass hours west of UTC, e.g. 5 or 4")
    y, m, d = (int(v) for v in datestr.split("-"))
    if clock is None:
        nxt = datetime.date(y, m, d) + datetime.timedelta(days=1)
        return "%sT%02d:59:59" % (nxt.isoformat(), utc_offset - 1), datestr, "true"
    hh, mm = (int(v) for v in clock.split(":"))
    return "%sT%02d:%02d:00" % (datestr, hh + utc_offset, mm), datestr, "false"


def set_due(assignment_xml, due_at, all_day_date, all_day):
    """Write the three date fields into an assignment_settings.xml string.

    Handles both the self-closing empty form Canvas writes for an assignment
    with no date (<due_at/>) and a populated element.
    """
    x = re.sub(r"<due_at\s*/>|<due_at>.*?</due_at>",
               "<due_at>%s</due_at>" % due_at, assignment_xml, count=1)
    if re.search(r"<all_day_date\s*/>|<all_day_date>", x):
        x = re.sub(r"<all_day_date\s*/>|<all_day_date>.*?</all_day_date>",
                   "<all_day_date>%s</all_day_date>" % all_day_date, x, count=1)
    else:
        # Canvas writes all_day_date only when there is a date to write, so a
        # freshly built assignment may not have the element at all. Insert it
        # after due_at, where real exports put it.
        x = re.sub(r"(</due_at>)",
                   r"\1\n  <all_day_date>%s</all_day_date>" % all_day_date, x, count=1)
    x = re.sub(r"<all_day\s*/>|<all_day>.*?</all_day>",
               "<all_day>%s</all_day>" % all_day, x, count=1)
    return x


# ---------------------------------------------------------------------------
# Rubrics
# ---------------------------------------------------------------------------
CCX = "{http://canvas.instructure.com/xsd/cccv1p0}"


def rewrite_rubric(rubric_el, criteria, title=None, ns=CCX):
    """Replace a rubric's criteria in place, keeping its rating scales.

    `criteria` is [(description, points), ...] in the order they should
    appear. `rubric_el` is one <rubric> element from
    course_settings/rubrics.xml, mutated in place.

    Use this rather than zipping your new list against the elements already
    there. That obvious version has two bugs, both of which import silently
    and are invisible until someone grades with the rubric.

    ONE: a criterion past the end of the old list is dropped without a word.
    A rubric that went from three criteria to four imported totalling 80
    against a 100-point assignment. Extras here are deep-copied from the last
    criterion, so they inherit its rating scale, and are given fresh ids.

    TWO: rescaling a rating by old/oldmax*new AFTER writing the new value into
    the criterion makes oldmax == new, so every rating divides by itself and
    keeps last term's numbers. A criterion cut from 40 points to 30 still
    topped out at a 40-point "Excellent". The old maximum is read here before
    anything is overwritten.

    Raises SystemExit if the new criteria do not sum to the rubric's own
    points_possible, because a rubric that does not add up is not a thing you
    want to discover from a gradebook.
    """
    if title is not None:
        el = rubric_el.find(ns + "title")
        if el is not None:
            el.text = title

    holder = rubric_el.find(ns + "criteria")
    existing = list(holder) if holder is not None else []
    if not existing:
        raise SystemExit("rubric %r has no criteria to rewrite"
                         % (rubric_el.findtext(ns + "title") or "?"))

    for i, (desc, pts) in enumerate(criteria):
        if i < len(existing):
            c = existing[i]
        else:
            c = copy.deepcopy(existing[-1])
            cid = "_cck%d" % (i + 1)
            el = c.find(ns + "criterion_id")
            if el is not None:
                el.text = cid
            for rat in c.findall(ns + "ratings"):
                for j, r in enumerate(rat):
                    el = r.find(ns + "criterion_id")
                    if el is not None:
                        el.text = cid
                    el = r.find(ns + "id")
                    if el is not None:
                        el.text = "%s_r%d" % (cid, j)
            holder.append(c)

        d = c.find(ns + "description")
        p = c.find(ns + "points")
        try:
            oldmax = float(p.text) if p is not None and p.text else 0.0
        except ValueError:
            oldmax = 0.0
        if d is not None:
            d.text = desc
        if p is not None:
            p.text = "%.1f" % pts
        for rat in c.findall(ns + "ratings"):
            for r in rat:
                el = r.find(ns + "criterion_description")
                if el is not None:
                    el.text = desc
                el = r.find(ns + "points")
                if el is not None and oldmax:
                    try:
                        el.text = "%.1f" % (float(el.text) / oldmax * pts)
                    except (TypeError, ValueError):
                        pass

    for extra in list(holder)[len(criteria):]:
        holder.remove(extra)

    total = sum(p for _, p in criteria)
    pp_el = rubric_el.find(ns + "points_possible")
    try:
        pp = float(pp_el.text) if pp_el is not None and pp_el.text else 0.0
    except ValueError:
        pp = 0.0
    if pp and abs(total - pp) > 0.001:
        raise SystemExit(
            "rubric %r criteria sum to %g but points_possible is %g"
            % (rubric_el.findtext(ns + "title") or "?", total, pp))
    return rubric_el


# ---------------------------------------------------------------------------
# Finding things in a package
# ---------------------------------------------------------------------------
# A module item in course_settings/module_meta.xml.
ITEM_RE = re.compile(r"[ \t]*<item identifier=\"[^\"]+\">.*?</item>\n", re.S)

# A LEAF item in the manifest's <organizations> tree. Only leaves carry
# identifierref, so this never matches a module wrapper and never has to nest.
ORG_ITEM_RE = re.compile(
    r"[ \t]*<item identifier=\"[^\"]+\" identifierref=\"[^\"]+\">.*?</item>\n", re.S)


def org_module_re(title):
    """A MODULE in the manifest organizations tree.

    A module there is an <item> carrying a title and child <item>s and no
    identifierref, so it is matched by title and its own closing indent.
    ORG_ITEM_RE cannot be used: it only ever matches leaves, and a naive
    non-greedy pattern would truncate a module at its first child's </item>.
    """
    return re.compile(
        r'([ \t]*)<item identifier="[^"]+">\n\s*<title>%s</title>\n(.*?)\n\1</item>\n'
        % re.escape(title), re.S)


def assignment_titles(z):
    """{zip path of assignment_settings.xml: title} for every assignment."""
    out = {}
    for nm in z.namelist():
        if nm.endswith("/assignment_settings.xml"):
            m = re.search(r"<title>(.*?)</title>", z.read(nm).decode("utf8", "replace"))
            out[nm] = _html.unescape(m.group(1)) if m else "?"
    return out


def resource_id_for(man, href):
    """The resource identifier declaring a given href.

    Attribute order in imsmanifest.xml is NOT fixed: Canvas writes page
    resources as <resource identifier=... type=... href=...> and file
    resources as <resource type=... identifier=... href=...>. Any regex that
    assumes one order silently under-reports. Match the block, then look
    inside it.
    """
    for block in re.findall(r"<resource\b[^>]*>", man):
        if 'href="%s"' % xml_href(href) in block or 'href="%s"' % href in block:
            m = re.search(r'identifier="([^"]+)"', block)
            if m:
                return m.group(1)
    return None


def announcement_resources(z, man, titles_to_drop):
    """(resource ids, file paths) for announcements you want removed.

    Announcements come in PAIRS: each is an imsdt_xmlv1p1 topic resource plus
    an associatedcontent meta resource it names in a <dependency>. Removing
    only the topic leaves the manifest pointing at an orphan. Both resources
    and both .xml files have to go.

    Note a discussion topic (<type>topic</type>) is not an announcement
    (<type>announcement</type>) and may well be a real module item you want
    to keep.
    """
    refs, files, found = set(), set(), set()
    for block in re.findall(r'<resource\b[^>]*type="imsdt_xmlv1p1"[^>]*>.*?</resource>',
                            man, re.S):
        topic_id = re.search(r'identifier="([^"]+)"', block).group(1)
        topic_file = re.search(r'<file href="([^"]+)"', block).group(1)
        title = _html.unescape(re.search(r"<title>(.*?)</title>",
                                         z.read(topic_file).decode(), re.S).group(1))
        if title not in titles_to_drop:
            continue
        found.add(title)
        refs.add(topic_id)
        files.add(topic_file)
        for dep in re.findall(r'<dependency identifierref="([^"]+)"', block):
            refs.add(dep)
            files.add(dep + ".xml")
    missing = set(titles_to_drop) - found
    if missing:
        raise SystemExit("announcements marked for removal not found: %s" % sorted(missing))
    return refs, files


def weblink_resources(z, man, titles_to_drop):
    """(resource ids, file paths) for ExternalUrl links you want removed.

    An ExternalUrl module item is only the visible half. Each link is also an
    imswl_xmlv1p1 resource with its own .xml file. Dropping the module item
    alone leaves the resource orphaned in the package, and no structural check
    will notice.
    """
    refs, files, found = set(), set(), set()
    for block in re.findall(r'<resource\b[^>]*type="imswl_xmlv1p1"[^>]*>.*?</resource>',
                            man, re.S):
        ref = re.search(r'identifier="([^"]+)"', block).group(1)
        f = re.search(r'<file href="([^"]+)"', block).group(1)
        title = _html.unescape(re.search(r"<title>(.*?)</title>",
                                         z.read(f).decode(), re.S).group(1))
        if title in titles_to_drop:
            found.add(title)
            refs.add(ref)
            files.add(f)
    missing = set(titles_to_drop) - found
    if missing:
        raise SystemExit("weblinks marked for removal not found: %s" % sorted(missing))
    return refs, files


def emptied_dirs(names, moved, dropped):
    """Directory entries whose every child has moved away or been dropped.

    A zip records folders as their own entries. Move every file out and the
    folder is still listed, so Canvas still shows an empty folder in Files.
    """
    out = set()
    for d in {n for n in names if n.endswith("/")}:
        children = [n for n in names if n != d and n.startswith(d)]
        if children and all(n in moved or n in dropped for n in children):
            out.add(d)
    return out


# ---------------------------------------------------------------------------
# Streaming the rewrite
# ---------------------------------------------------------------------------
def stream_rewrite(src, out, *, drop=(), replace=None, add=None,
                   rename=None, transform=None):
    """Copy src.imscc to out.imscc, changing only what you name.

    drop       iterable of zip entry names to omit entirely
    replace    {entry name: bytes} to write instead of the original
    add        {entry name: bytes} to append as new entries
    rename     {old entry name: new entry name} for moved files
    transform  callable(name, data) -> bytes, applied to everything else that
               is not dropped or replaced. Return data unchanged to pass it
               through.

    Nothing is unpacked, so package size costs time but not disk or memory.

    If a renamed file lands on a path that already exists, the first one wins
    and the second is dropped. That is the deduplication case, and it is
    deliberate: two manifest resources declaring the same href is invalid.
    """
    drop = set(drop)
    replace = replace or {}
    add = add or {}
    rename = rename or {}
    written = set()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            nm = info.filename
            if nm in drop:
                continue
            dest = rename.get(nm, nm)
            if dest in written:
                continue
            written.add(dest)
            if nm in replace:
                data = replace[nm]
            else:
                data = zin.read(nm)
                if transform is not None:
                    data = transform(nm, data)
            zout.writestr(dest, data)
        for nm, data in add.items():
            if nm not in written:
                zout.writestr(nm, data)


def diff_packages(a, b):
    """(added, removed, modified) entry names between two packages.

    Verify a mutation by diffing the result against the source rather than by
    trusting your own checks. This is the round-trip rule applied before
    import instead of after, and it is what catches an edit that reached more
    entries than you intended.
    """
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        ha = {i.filename: i.CRC for i in za.infolist()}
        hb = {i.filename: i.CRC for i in zb.infolist()}
    added = sorted(set(hb) - set(ha))
    removed = sorted(set(ha) - set(hb))
    modified = sorted(n for n in set(ha) & set(hb) if ha[n] != hb[n])
    return added, removed, modified


def assert_xml_parses(path):
    """Parse every .xml in a finished package. Do this before anything else.

    A path rewrite once wrote a bare & into an href, making imsmanifest.xml
    invalid XML. Every regex check still passed: resources were declared,
    hrefs resolved, references matched. But no parser could read the manifest,
    so nothing could build a resource map, and every module item rendered as
    inert unclickable text in both the cartridge viewer and Canvas.
    """
    bad = []
    with zipfile.ZipFile(path) as z:
        for nm in sorted(n for n in z.namelist() if n.endswith(".xml")):
            try:
                ET.fromstring(z.read(nm))
            except ET.ParseError as exc:
                bad.append((nm, str(exc)))
    if bad:
        raise SystemExit("XML is not well-formed:\n" +
                         "\n".join("  %s -> %s" % b for b in bad))
