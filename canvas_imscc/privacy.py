#!/usr/bin/env python3
"""Flag things in a package that may carry student data. Report only.

    python3 -m canvas_imscc.privacy "My Course.imscc"

WHAT THIS IS
------------
A triage aid, not a compliance check. It cannot tell you whether a package is
FERPA-compliant, because that is a legal determination about your institution's
records and not something a script decides. What it can do is point at the
handful of places student identity actually hides in a Canvas package, so a
human spends two minutes looking instead of hoping.

It NEVER modifies the package and NEVER changes an exit status. A privacy
warning is a prompt to look, and a checker that blocks a build over a
false positive is a checker people switch off.

WHY THE LIST IS SHORT
---------------------
A Canvas *Course* export contains no student records: no submissions, no
gradebook, no enrollments, no discussion posts. Verified against a real export
of a course that had run. So most of what you might fear is simply not in the
file. What leaks is identity embedded incidentally in CONTENT, and that is what
this looks for.

Findings are graded by how much a human should trust them:

  review   Something that should not be in a Course export at all. Rare, and
           worth stopping for: it usually means the wrong export type, or a
           file dragged in by hand.
  look     A real pattern with real false positives. Your own email address
           will match. That is fine; you will recognise it in one second, which
           is the entire point.

Deliberately NOT attempted: guessing whether a string is a person's name.
Name detection is noisy in exactly the way that trains people to ignore a
report, and a privacy sweep nobody reads is worse than none.
"""
import argparse
import html as _html
import os
import re
import sys

from .accessibility import Finding, _iter_entries, _escaped_bodies

__all__ = ["audit_privacy", "format_privacy_report"]

# Paths that have no business in a Course export. Canvas ships student work
# through a different export entirely, so any of these means either the wrong
# export type or a file someone added by hand.
BAD_PATH = re.compile(
    r"(^|/)(submissions?|gradebook|grades?|roster|enrollments?)(/|[-_.])"
    r"|(^|/)[^/]*grade[^/]*\.(csv|xlsx?|tsv)$"
    r"|(^|/)[^/]*roster[^/]*\.(csv|xlsx?|tsv)$", re.I)

# Spreadsheets are how grades and rosters travel. Worth a glance wherever they
# turn up in course files.
SHEET = re.compile(r"\.(csv|xlsx?|tsv)$", re.I)

# XML elements that describe PEOPLE rather than configuration. A course export
# has none of these; assignment settings like grader_count look similar and are
# excluded by requiring an id/name/login shape.
USER_ELEMENT = re.compile(
    r"<((?:user|student|enrollment|submitter|author)_(?:id|name|login|email)"
    r"|user|enrollment|submission)\b", re.I)

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Canvas names an upload from the Student app "Firstname Lastname - Mon DD,
# YYYY HHMM AM". That shape is specific enough to call out on its own, and it
# is how a real student name was found sitting in alt text in a live course.
# A plain "two capitalised words" test cannot do this job: every art history
# page is full of artist names.
CANVAS_UPLOAD = re.compile(
    r"[A-Z][a-z]+ [A-Z][a-z]+ - [A-Z][a-z]{2} \d{1,2}, \d{4}")

# The submission naming convention instructors actually hand out, e.g.
# ART226_Firstname_Lastname.pdf or ART 209 - Lastname, Firstname.jpg. Requires
# two capitalised alphabetic tokens so ordinary words do not match.
# NOT case-insensitive, and that is the whole point: the capitals are the
# signal. Compiling this with re.I makes [A-Z] match lowercase too, and
# "Antonio Lopez Garcia, Sick, charcoal.jpg" is then read as a student named
# Sick Charcoal. Only the file extension is case-folded.
STUDENT_FILE = re.compile(
    r"[A-Z]{2,4}\s?\d{3}[ _-]+[A-Z][a-z]+[ _,-]+[A-Z][a-z]+"
    r"|[A-Z][a-z]+[ ]?,[ ]?[A-Z][a-z]+\s*\.(?i:jpe?g|png|pdf|tiff?|heic)$")


def audit_privacy(path):
    """Return (findings, counts). Reads the package; never writes to it."""
    findings = []
    counts = {"entries": 0, "text": 0}

    def add(sev, code, where, detail):
        findings.append(Finding(sev, code, where, detail))

    def wanted(name):
        return True                      # entry NAMES matter as much as bodies

    seen_paths = []
    for name, data in _iter_entries(path, wanted):
        counts["entries"] += 1
        low = name.lower()
        seen_paths.append(name)

        if BAD_PATH.search(name):
            add("review", "ferpa-student-records-path", name,
                "a Course export should contain no submissions, gradebook or "
                "roster. Check whether this is the right export type, or "
                "whether the file was added by hand")
        elif SHEET.search(low) and low.startswith("web_resources/"):
            add("look", "ferpa-spreadsheet-in-files", name,
                "a spreadsheet in course Files. Grades and rosters travel this "
                "way; confirm this one does not")

        if STUDENT_FILE.search(os.path.basename(name)):
            add("look", "ferpa-submission-filename", name,
                "the filename follows a student submission convention. Student "
                "work uploaded as an example keeps the name it arrived with")

        if not low.endswith((".html", ".htm", ".xml", ".txt")):
            continue
        text = data.decode("utf8", "replace")
        counts["text"] += 1

        if name.endswith(".xml"):
            m = USER_ELEMENT.search(text)
            if m:
                add("review", "ferpa-user-records", name,
                    "XML describes people, not settings (<%s>). A Course "
                    "export has no user records" % m.group(1))

        bodies = [text] + list(_escaped_bodies(text)) if name.endswith(".xml") \
            else [text]
        for body in bodies:
            for addr in set(EMAIL.findall(body)):
                add("look", "ferpa-email-address", name,
                    "email address in page content: %s (your own address will "
                    "match, and that is fine)" % addr)

    # Alt text holding a filename is an accessibility error already. It is
    # listed here too because it is the specific way a student's name survives
    # after the file itself was renamed: Canvas copies the original filename
    # into <img alt> on import.
    from .accessibility import audit_package as a11y_audit
    a11y, _ = a11y_audit(path, skip_pdfs=True)
    for f in a11y:
        if f.code != "img-alt-filename":
            continue
        alt = f.detail.split(": ", 1)[-1]
        if CANVAS_UPLOAD.search(alt):
            add("review", "ferpa-name-in-alt-text", f.where,
                "alt text carries a person's name and an upload timestamp, "
                "which is how Canvas names a file uploaded from the Student "
                "app: %s" % alt)
        else:
            add("look", "ferpa-filename-in-alt-text", f.where,
                "alt text is a filename rather than a description: %s. "
                "Harmless for an artwork; this is also the place a student's "
                "name survives after the file itself was renamed" % alt)

    return findings, counts


def format_privacy_report(findings, counts=None, limit_per_code=8):
    lines = []
    if counts:
        lines.append("scanned %d entries, %d with readable text"
                     % (counts.get("entries", 0), counts.get("text", 0)))
    if not findings:
        lines.append("nothing flagged. This is NOT a statement that the "
                     "package is FERPA-compliant; see the module docstring.")
        return "\n".join(lines)

    by = {}
    for f in findings:
        by.setdefault((f.severity, f.code), []).append(f)
    order = sorted(by, key=lambda k: (k[0] != "review", -len(by[k]), k[1]))
    n_rev = sum(1 for f in findings if f.severity == "review")
    lines.append("%d to review, %d to look at. Nothing here blocks anything; "
                 "these are prompts for a human." % (n_rev, len(findings) - n_rev))
    lines.append("Do not paste this report into a bug report or a ticket.")
    for sev, code in order:
        g = by[(sev, code)]
        lines.append("")
        lines.append("%-6s %s  (%d)" % (sev.upper(), code, len(g)))
        for f in g[:limit_per_code]:
            lines.append("    %s" % f.where)
            lines.append("        %s" % f.detail)
        if len(g) > limit_per_code:
            lines.append("    ... and %d more" % (len(g) - limit_per_code))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help=".imscc, an unzipped export directory, or a file")
    ap.add_argument("--all", action="store_true",
                    help="list every finding instead of capping each code")
    a = ap.parse_args(argv)
    findings, counts = audit_privacy(a.target)
    print(format_privacy_report(findings, counts,
                                limit_per_code=10 ** 6 if a.all else 8))
    return 0                              # never blocks, by design


if __name__ == "__main__":
    sys.exit(main())
