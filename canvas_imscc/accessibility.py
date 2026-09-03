#!/usr/bin/env python3
"""Accessibility audit for a Canvas package, aimed at what Ally scores.

    python3 -m canvas_imscc.accessibility "My Course.imscc"
    python3 -m canvas_imscc.accessibility ./unzipped-export --strict
    python3 -m canvas_imscc.accessibility course.imscc --ignore img-alt-vague

Runs against a .imscc, an unzipped export directory, or a single .html file.
No dependencies.

WHY THIS IS SEPARATE FROM validate_package
------------------------------------------
Every check in validate_package.py exists because a package silently failed to
IMPORT correctly. These checks are different in kind: the package imports fine
and the course works, but some students cannot use it. So they are reported
separately and, by default, do NOT change exit status. Fold them into the
structural checks and either you block builds over a missing alt attribute or,
far more likely, people learn to ignore the whole validator. Pass --strict (or
a11y_strict=True) in CI once a course is clean, to keep it clean.

WHAT THIS CANNOT DO
-------------------
An automated checker reaches perhaps half of WCAG. It cannot tell you whether
alt text is *accurate*, whether a video's captions are correct rather than
merely present, whether colour is the only thing carrying a distinction, or
whether reading order makes sense. A clean report here is a floor, not a pass.
The checks below are therefore split into errors, which are machine-decidable
failures, and warnings, which mean "a human has to look at this."

PDFs ARE REPORTED, NEVER MODIFIED
---------------------------------
Untagged PDFs are usually the largest part of a low Ally score, so the audit
inventories them. It does not rewrite them: producing a real structure tree is
not something to fake, and setting /MarkInfo /Marked true without one makes a
file CLAIM to be tagged, which turns some checkers green while a screen reader
still gets nothing. Remediate PDFs in a tool built for it, or replace them with
HTML, which you control completely.
"""
import argparse
import html as _html
import io
import os
import pathlib
import re
import sys
import zipfile
import zlib
from html.parser import HTMLParser

__all__ = ["Finding", "audit_html", "audit_pdf", "audit_package", "format_report"]

_CONTRAST = "\x00contrast:"

VOID = {"img", "br", "hr", "input", "meta", "link", "source", "track", "col", "area"}

# Link text that describes nothing once it is out of context. A screen reader
# user can pull up a list of every link on the page; "click here" nine times is
# what that list becomes.
EMPTY_LINK_TEXT = {
    "click here", "click", "here", "read more", "more", "link", "this link",
    "this", "go", "download", "see here", "learn more", "continue", "info",
}

# Alt text that passes a "has alt" check and tells a blind student nothing.
VAGUE_ALT = {
    "image", "photo", "picture", "graphic", "img", "figure", "illustration",
    "screenshot", "diagram", "photograph", "artwork", "example", "untitled",
}
VAGUE_ALT_PREFIX = ("image of", "picture of", "photo of", "graphic of",
                    "screenshot of", "an image", "a photo", "a picture")
# Canvas copies the original filename into <img alt> on import, so a great many
# real courses carry alt text like "Screen%20Shot%202024-01-02%20at%2011.09.13".
FILENAME_ALT = re.compile(
    r"(\.(jpe?g|png|gif|webp|svg|bmp|tiff?|heic)\s*$)|%20|_{2,}|^\S+_\S+_\S+$", re.I)


class Finding(object):
    """One problem, in one place. severity is 'error' or 'warning'."""

    __slots__ = ("severity", "code", "where", "detail")

    def __init__(self, severity, code, where, detail):
        self.severity = severity
        self.code = code
        self.where = where
        self.detail = detail

    def __repr__(self):
        return "Finding(%r, %r, %r, %r)" % (
            self.severity, self.code, self.where, self.detail)

    def __str__(self):
        return "%-7s %-18s %s: %s" % (
            self.severity.upper(), self.code, self.where, self.detail)


# --------------------------------------------------------------------------
# colour, for contrast
# --------------------------------------------------------------------------

NAMED_COLOURS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "maroon": (128, 0, 0),
    "navy": (0, 0, 128), "teal": (0, 128, 128), "olive": (128, 128, 0),
    "lime": (0, 255, 0), "aqua": (0, 255, 255), "cyan": (0, 255, 255),
    "fuchsia": (255, 0, 255), "magenta": (255, 0, 255),
}


def parse_colour(text):
    """'#abc', '#aabbcc', 'rgb(1,2,3)' or a common name -> (r, g, b) or None.

    Returns None rather than guessing. An unparsed colour must not be silently
    treated as black, because that invents contrast failures that are not
    there, and a checker that cries wolf gets switched off.
    """
    if not text:
        return None
    t = text.strip().lower()
    if t in NAMED_COLOURS:
        return NAMED_COLOURS[t]
    m = re.match(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", t)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", t)
    if m:
        try:
            return tuple(min(255, max(0, int(round(float(g))))) for g in m.groups())
        except ValueError:
            return None
    return None


def _channel(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    r, g, b = (_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    """WCAG 2.1 contrast ratio, 1.0 to 21.0."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _declarations(style):
    out = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _is_large_text(decls, tag):
    """WCAG 'large text' is >=18pt, or >=14pt bold. 1pt ~ 1.333px."""
    if tag in ("h1", "h2", "h3"):
        return True
    size = decls.get("font-size", "")
    weight = decls.get("font-weight", "").lower()
    bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 700)
    m = re.match(r"^([\d.]+)\s*(px|pt|em|rem|%)?$", size.strip())
    if not m:
        return False
    try:
        n = float(m.group(1))
    except ValueError:
        return False
    unit = m.group(2) or "px"
    pt = {"px": n * 0.75, "pt": n, "em": n * 12, "rem": n * 12,
          "%": n * 0.12}.get(unit, 0)
    return pt >= 18 or (bold and pt >= 14)


# --------------------------------------------------------------------------
# the HTML pass
# --------------------------------------------------------------------------

class _Collector(HTMLParser):
    """Pulls out the handful of structures the checks reason about.

    Parsing rather than pattern-matching is deliberate. A regex for <img>
    without alt cannot see an alt attribute that contains a > inside a quoted
    value, and reports a clean page as broken; the reverse mistake, matching
    only the first <img> on a line, reports a broken page as clean. Both have
    happened to checkers in this repo's history, which is why the structural
    validator parses XML too.
    """

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.images = []        # (src, alt or None, in_link)
        self.headings = []      # (level, text)
        self.links = []         # (href, text, had_img_alt)
        self.tables = []        # dict(th, scoped_th, caption, rows)
        self.iframes = []       # (src, title)
        self.media = []         # description of an embed needing captions
        self.contrast = []      # (fg, bg, tag, large, sample)
        self.fake_headings = []  # text of a paragraph that is entirely bold
        self.fake_lists = []    # text of a paragraph that starts with a bullet
        self._para_bold = []    # bold text accumulated inside the current <p>
        self._stack = []        # open tags we track
        self._bg = [(255, 255, 255)]
        self._buf = None        # text accumulator for the innermost capture
        self._captures = []     # (tag, level_or_none, buf_index)
        self._bufs = []
        self._table = None
        self._para_children = []

    # -- helpers -----------------------------------------------------------
    def _push_capture(self, tag):
        self._bufs.append([])
        self._captures.append(tag)

    def _pop_capture(self):
        if not self._captures:
            return None, ""
        tag = self._captures.pop()
        return tag, "".join(self._bufs.pop()).strip()

    def _emit_text(self, data):
        if self._bufs:
            self._bufs[-1].append(data)

    # -- parser callbacks --------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict((k.lower(), (v if v is not None else "")) for k, v in attrs)
        decls = _declarations(a.get("style", ""))

        bg = parse_colour(decls.get("background-color") or decls.get("background"))
        self._bg.append(bg or self._bg[-1])
        fg = parse_colour(decls.get("color"))

        if tag == "img":
            self.images.append((a.get("src", ""), a.get("alt"),
                                any(c == "a" for c in self._captures)))
            if a.get("alt"):
                self._emit_text(a["alt"])
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._push_capture(tag)
        elif tag == "a":
            self._push_capture("a")
            self._stack.append(("a", a.get("href", "")))
        elif tag == "p":
            # HTML lets <p> close implicitly, and real Canvas page bodies are
            # full of unclosed ones. HTMLParser does not do that for us, so a
            # run of unclosed paragraphs would nest into a single capture and
            # every check that reads paragraph text would go quiet.
            if self._captures and self._captures[-1] == "p":
                self.handle_endtag("p")
            self._push_capture("p")
            self._para_children.append([])
            self._para_bold.append([])
        elif tag in ("strong", "b"):
            if self._para_children:
                self._para_children[-1].append(tag)
            self._push_capture("__bold__")
        elif tag in ("em", "i", "span"):
            if self._para_children:
                self._para_children[-1].append(tag)
        elif tag == "table":
            self._table = {"th": 0, "scoped_th": 0, "caption": False,
                           "rows": 0, "cols_first_row": 0}
            self.tables.append(self._table)
        elif tag == "caption" and self._table is not None:
            self._table["caption"] = True
        elif tag == "tr" and self._table is not None:
            self._table["rows"] += 1
        elif tag == "th" and self._table is not None:
            self._table["th"] += 1
            if a.get("scope", "").strip():
                self._table["scoped_th"] += 1
        elif tag == "iframe":
            self.iframes.append((a.get("src", ""), a.get("title", "").strip()))
            if re.search(r"youtube|youtu\.be|vimeo|kaltura|panopto|echo360|"
                         r"instructuremedia|arc\.", a.get("src", ""), re.I):
                self.media.append("iframe " + a.get("src", "")[:80])
        elif tag in ("video", "audio"):
            self.media.append("<%s> element" % tag)

        # Pushed LAST so it is the innermost capture and pops FIRST, which
        # keeps it from interleaving with the per-tag captures above. Getting
        # this order wrong leaks a capture on every styled <p> and every
        # heading text afterwards lands in the wrong buffer.
        if fg is not None:
            self.contrast.append([fg, self._bg[-1], tag,
                                  _is_large_text(decls, tag), None])
            self._push_capture(_CONTRAST + tag)

        if tag in VOID:
            self._bg.pop()
            if fg is not None:
                self._pop_capture()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if len(self._bg) > 1:
            self._bg.pop()

        if self._captures and self._captures[-1] == _CONTRAST + tag:
            _, text = self._pop_capture()
            for rec in reversed(self.contrast):
                if rec[4] is None and rec[2] == tag:
                    rec[4] = text[:60]
                    break
            self._emit_text(text)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._captures and self._captures[-1] == tag:
                _, text = self._pop_capture()
                self.headings.append((int(tag[1]), text))
                self._emit_text(text)
        elif tag == "a":
            if self._captures and self._captures[-1] == "a":
                _, text = self._pop_capture()
                href = ""
                for i in range(len(self._stack) - 1, -1, -1):
                    if self._stack[i][0] == "a":
                        href = self._stack.pop(i)[1]
                        break
                self.links.append((href, text))
                self._emit_text(text)
        elif tag in ("strong", "b"):
            if self._captures and self._captures[-1] == "__bold__":
                _, text = self._pop_capture()
                if self._para_bold:
                    self._para_bold[-1].append(text)
                self._emit_text(text)
        elif tag == "p":
            if self._captures and self._captures[-1] == "p":
                _, text = self._pop_capture()
                self._para_children.pop() if self._para_children else None
                bold = " ".join(self._para_bold.pop()) if self._para_bold else ""
                # A faked heading is a paragraph that is ENTIRELY bold, short,
                # and unpunctuated. Requiring "contains a <strong>" instead
                # flagged every callout banner whose first word is bold, which
                # is a false positive on correct markup.
                if (text and len(text) < 120 and len(text.split()) <= 12
                        and len(bold) >= 0.9 * len(text)
                        and not text.rstrip().endswith((".", "!", "?", ":"))):
                    self.fake_headings.append(text)
                if re.match(r"^\s*([-*•–]|\d+[.)])\s+\S", text):
                    self.fake_lists.append(text[:60])
                self._emit_text(text)
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        self._emit_text(data)


def audit_html(html, where=""):
    """Audit one HTML fragment or document. Returns a list of Finding."""
    out = []

    def err(code, detail):
        out.append(Finding("error", code, where, detail))

    def warn(code, detail):
        out.append(Finding("warning", code, where, detail))

    c = _Collector()
    try:
        c.feed(html)
        c.close()
    except Exception as exc:                       # noqa: BLE001
        # Never swallow this. A parser that dies quietly returns an empty
        # finding list, which reads exactly like a clean page.
        err("html-unparseable", "could not parse: %s" % exc)
        return out

    # -- images ------------------------------------------------------------
    for src, alt, _in_link in c.images:
        name = os.path.basename(src.split("?")[0])[:60] or "(no src)"
        if alt is None:
            err("img-no-alt", "<img> has no alt attribute: %s" % name)
            continue
        a = alt.strip()
        if not a:
            continue                    # alt="" is a valid decorative image
        if FILENAME_ALT.search(a) or a == name:
            err("img-alt-filename",
                "alt text is a filename, not a description: %r" % a[:60])
        elif a.lower() in VAGUE_ALT or a.lower().startswith(VAGUE_ALT_PREFIX):
            warn("img-alt-vague",
                 "alt text describes nothing specific: %r" % a[:60])
        elif len(a) < 6:
            warn("img-alt-short", "alt text is %d characters: %r" % (len(a), a))

    # -- headings ----------------------------------------------------------
    prev = 0
    for level, text in c.headings:
        if not text:
            err("heading-empty", "empty <h%d>" % level)
        if level == 1:
            # Canvas renders the page or assignment title as the page's h1, so
            # an h1 in the body gives the page two competing top-level
            # headings. Start bodies at h2.
            warn("heading-h1-in-body",
                 "body contains <h1> %r; Canvas already renders the page "
                 "title as h1" % text[:50])
        if prev and level > prev + 1:
            err("heading-skipped-level",
                "jumps from h%d to h%d at %r" % (prev, level, text[:50]))
        prev = level
    for text in c.fake_headings:
        warn("heading-faked-with-bold",
             "bold paragraph used as a heading: %r" % text[:60])

    # -- links -------------------------------------------------------------
    for href, text in c.links:
        t = " ".join(text.split())
        if not t:
            err("link-no-text",
                "link has no text and no image alt: %s" % (href[:60] or "(no href)"))
        elif t.lower().strip(" .:!?") in EMPTY_LINK_TEXT:
            err("link-text-meaningless",
                "link text %r says nothing out of context (-> %s)" % (t, href[:50]))
        elif re.match(r"^\s*(https?://|www\.)", t):
            warn("link-text-is-url",
                 "link text is a raw URL, which a screen reader reads out "
                 "character by character: %r" % t[:60])

    # -- tables ------------------------------------------------------------
    for i, tb in enumerate(c.tables, 1):
        if tb["rows"] <= 1 and tb["th"] == 0:
            warn("table-layout",
                 "table %d has no headers and one row; if it is being used "
                 "for layout, use CSS instead" % i)
        elif tb["th"] == 0:
            err("table-no-headers",
                "table %d (%d rows) has no <th>, so every cell is orphaned "
                "from its column" % (i, tb["rows"]))
        elif tb["scoped_th"] < tb["th"]:
            warn("table-th-no-scope",
                 "table %d has %d <th> but %d carry scope=\"col\"/\"row\""
                 % (i, tb["th"], tb["scoped_th"]))
        if tb["th"] and not tb["caption"]:
            warn("table-no-caption",
                 "table %d has no <caption> naming what it holds" % i)

    # -- embedded media ----------------------------------------------------
    for src, title in c.iframes:
        if not title:
            err("iframe-no-title",
                "<iframe> has no title attribute: %s" % (src[:60] or "(no src)"))
    for m in c.media:
        warn("media-captions-unverifiable",
             "%s needs captions and a transcript; no checker can confirm "
             "they exist and are correct" % m)

    # -- contrast ----------------------------------------------------------
    for fg, bg, tag, large, sample in c.contrast:
        if fg is None or bg is None:
            continue
        ratio = contrast_ratio(fg, bg)
        need = 3.0 if large else 4.5
        if ratio < need:
            err("contrast-too-low",
                "#%02x%02x%02x on #%02x%02x%02x is %.1f:1, below %.1f:1 "
                "for this text size (%r)"
                % (fg[0], fg[1], fg[2], bg[0], bg[1], bg[2], ratio, need,
                   (sample or tag)[:40]))

    # -- lists -------------------------------------------------------------
    for text in c.fake_lists:
        warn("list-faked-with-text",
             "paragraph starts like a list item but is not in <ul>/<ol>: %r"
             % text)

    return out


# --------------------------------------------------------------------------
# PDFs: reported, never modified
# --------------------------------------------------------------------------

def audit_pdf(data, where=""):
    """Report a PDF's accessibility metadata. Read-only, by design.

    Looks in the raw bytes and then inside compressed object streams, because
    a modern PDF keeps its document catalog in an object stream, so a plain
    byte search reports every tagged file as untagged.
    """
    tagged = b"/StructTreeRoot" in data
    lang = b"/Lang" in data
    title = re.search(rb"/Title\s*[(<]", data) is not None
    if not (tagged and lang):
        for m in re.finditer(rb"stream\r?\n", data):
            s = m.end()
            e = data.find(b"endstream", s)
            if e < 0 or e - s > 4_000_000:
                continue
            try:
                obj = zlib.decompress(data[s:e])
            except Exception:                      # noqa: BLE001
                continue
            tagged = tagged or b"/StructTreeRoot" in obj
            lang = lang or b"/Lang" in obj
            title = title or re.search(rb"/Title\s*[(<]", obj) is not None
            if tagged and lang and title:
                break

    out = []
    if not tagged:
        out.append(Finding(
            "error", "pdf-untagged", where,
            "no structure tree: a screen reader gets no headings, no reading "
            "order and no alt text. Remediate in Acrobat, request an "
            "accessible copy from the publisher, or replace it with an HTML "
            "page"))
    if not lang:
        out.append(Finding("warning", "pdf-no-language", where,
                           "no document language set"))
    if not title:
        out.append(Finding("warning", "pdf-no-title", where,
                           "no document title set; the filename is read instead"))
    return out


# --------------------------------------------------------------------------
# whole packages
# --------------------------------------------------------------------------

def _escaped_bodies(xml_text):
    """HTML bodies stored escaped inside <text texttype="text/html"> in XML.

    Discussions, announcements and assignment descriptions live here, not in
    .html files. A checker that scans only .html silently gives every
    discussion in the course a free pass, which is the same class of bug the
    structural validator's _carries_links() exists to prevent.
    """
    for m in re.finditer(
            r'<text[^>]*texttype="text/html"[^>]*>(.*?)</text>',
            xml_text, re.S):
        body = _html.unescape(m.group(1))
        if "<" in body:
            yield body


def _iter_entries(path, wanted):
    """Yield (name, bytes) for a .imscc, an unzipped directory, or one file.

    `wanted(name) -> bool` is applied BEFORE the bytes are read. That ordering
    is the whole point: a real course export is mostly PDFs, images and video,
    and reading every entry in order to then discard it on its extension turned
    a two-second audit of a 900 MB export into one that had to be killed.
    """
    p = pathlib.Path(path)
    if p.is_dir():
        for f in sorted(p.rglob("*")):
            rel = str(f.relative_to(p))
            if f.is_file() and not f.name.startswith("._") and wanted(rel):
                yield rel, f.read_bytes()
    elif zipfile.is_zipfile(str(p)):
        with zipfile.ZipFile(str(p)) as z:
            for name in sorted(z.namelist()):
                if not name.endswith("/") and wanted(name):
                    yield name, z.read(name)
    else:
        if wanted(p.name):
            yield p.name, p.read_bytes()


def audit_package(path, ignore=(), skip_pdfs=False):
    """Audit every HTML body and PDF in a package. Returns (findings, counts)."""
    findings = []
    counts = {"html": 0, "xml_bodies": 0, "pdf": 0}

    def wanted(name):
        low = name.lower()
        if low.endswith((".html", ".htm", ".xml")):
            return True
        return low.endswith(".pdf") and not skip_pdfs

    for name, data in _iter_entries(path, wanted):
        low = name.lower()
        if low.endswith((".html", ".htm")):
            counts["html"] += 1
            findings += audit_html(data.decode("utf8", "replace"), name)
        elif low.endswith(".xml"):
            text = data.decode("utf8", "replace")
            for i, body in enumerate(_escaped_bodies(text), 1):
                counts["xml_bodies"] += 1
                findings += audit_html(body, "%s [body %d]" % (name, i))
        elif low.endswith(".pdf") and not skip_pdfs:
            counts["pdf"] += 1
            findings += audit_pdf(data, name)
    if ignore:
        ignore = set(ignore)
        findings = [f for f in findings if f.code not in ignore]
    return findings, counts


def format_report(findings, counts=None, limit_per_code=8):
    """A report grouped by code, because one bad template makes 200 findings."""
    lines = []
    if counts:
        lines.append("scanned: %d html page(s), %d html body/bodies inside xml, "
                     "%d pdf(s)" % (counts.get("html", 0),
                                    counts.get("xml_bodies", 0),
                                    counts.get("pdf", 0)))
    if not findings:
        lines.append("no automated accessibility problems found "
                     "(this is a floor, not a pass: see the module docstring)")
        return "\n".join(lines)

    by_code = {}
    for f in findings:
        by_code.setdefault((f.severity, f.code), []).append(f)
    order = sorted(by_code, key=lambda k: (k[0] != "error", -len(by_code[k]), k[1]))
    n_err = sum(1 for f in findings if f.severity == "error")
    lines.append("%d error(s), %d warning(s)"
                 % (n_err, len(findings) - n_err))
    for sev, code in order:
        group = by_code[(sev, code)]
        lines.append("")
        lines.append("%s  %s  (%d)" % (sev.upper(), code, len(group)))
        for f in group[:limit_per_code]:
            lines.append("    %s" % f.where)
            lines.append("        %s" % f.detail)
        if len(group) > limit_per_code:
            lines.append("    ... and %d more" % (len(group) - limit_per_code))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help=".imscc, an unzipped export directory, "
                                  "or a single .html file")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if there are any errors (for CI)")
    ap.add_argument("--warnings-are-errors", action="store_true",
                    help="with --strict, fail on warnings too")
    ap.add_argument("--ignore", action="append", default=[], metavar="CODE",
                    help="suppress a check by code; repeatable")
    ap.add_argument("--skip-pdfs", action="store_true",
                    help="HTML only (PDF scanning reads whole files)")
    ap.add_argument("--all", action="store_true",
                    help="list every finding instead of capping each code")
    a = ap.parse_args(argv)

    findings, counts = audit_package(a.target, a.ignore, a.skip_pdfs)
    print(format_report(findings, counts,
                        limit_per_code=10 ** 6 if a.all else 8))
    if a.strict:
        bad = [f for f in findings
               if f.severity == "error" or a.warnings_are_errors]
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
