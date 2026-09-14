---
name: canvas-course-kit
description: "Build Canvas courses via .imscc Common Cartridge exports — no API access needed."
version: 1.0.0
author: Michael Loren Diaz
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Canvas, LMS, Education, Common-Cartridge, Course-Design, Imscc, Higher-Education]
    related_skills: [pdf, xlsx, ocr-and-documents]
---

# Canvas Course Kit

Build and mutate Canvas LMS courses by generating `.imscc` (Common Cartridge) export packages — the exact zip format Canvas itself produces. Import by hand through Canvas's Import Course Content screen. **No API token, no admin access required.**

## When to Use

Build a Canvas course when:
- Your institution has disabled personal API access tokens (the most common case)
- You need modules, pages, files, real assignments with gradebook integration, rubrics, weighted gradebook groups, and Classic Quizzes
- You are rolling a course forward from a previous term's export
- You want course content in version control instead of locked inside Canvas

Do NOT use when:
- A working Canvas API token exists (the API is far simpler)
- The instructor just needs a syllabus PDF (use the `pdf` skill)
- The course content already exists and just needs updating (maybe a `git push`, not a full rebuild)

## Prerequisites

A Python 3.8+ environment, no dependencies beyond stdlib.

**If the repo is cloned**, the source lives at `<repo>/canvas_imscc/` with:
- `builder.py` — the engine. Modules, pages, files, assignments, groups, rubrics, manifest writing, validation, zipping.
- `rollforward.py` — helpers for mutating an existing export (path encoding, due dates, body replacement).
- `validate_package.py` — standalone checker for any `.imscc`.
- `accessibility.py` — accessibility audit of every HTML body and PDF.
- `privacy.py` — flags possible student data (report only, never modifies).

**If the repo is NOT cloned**, the workflow is the same but the builder must be supplied separately.

## The Two Modes

Before writing anything, decide which job this is:

### Job A — Build from Scratch
Use `ImsccBuilder` from `canvas_imscc/builder.py`. Read `playbook.md` for full patterns.

### Job B — Mutate a Previous Export
If a prior term's version exists in Canvas, **ask the instructor to export it first** (Settings > Export Course Content > Course). Then **mutate that export** rather than rebuilding. `rollforward.py` handles path encoding, body replacement, and safe mutations. Say "there's an existing export — I'll mutate it" rather than rebuilding from scratch. This is usually the right answer and instructors do not expect it.

## Critical Rules (Always Follow)

These are the things that cost real time when broken. For reasoning, see `docs/playbook.md`; the rules are here:

1. **Validate BEFORE zipping AND after.** `b.validate()` then `b.zip_package()`. Then run `python3 -m canvas_imscc.validate_package your.imscc` on the finished file. A malformed `imsmanifest.xml` imports silently and renders everything as inert, unclickable text.

2. **`course_settings/canvas_export.txt` must be DECLARED as a resource in `imsmanifest.xml`.** Undeclared, Canvas uses the generic Common Cartridge importer: assignments become Pages with no gradebook column, weighted groups disappear, and every page file is dumped into Files as junk. `builder.py` does this automatically — do not hand-edit it.

3. **Always import into an EMPTY course shell.** Canvas never deletes on import. Re-importing duplicates everything. A bad import means the instructor ticking delete boxes one at a time per item, with no bulk option.

4. **Verify in TWO places because they can disagree.** First at [common-cartridge-viewer.netlify.app](https://common-cartridge-viewer.netlify.app/) (renders module tree, indent levels, page bodies). Then have the instructor use "Select specific content" (not "All content") so Canvas pauses and shows its own reading of the package. A package can look correct in the viewer and still import as broken in Canvas.

5. **Never invent a URL from a pattern.** Check each one with `curl -I` or `requests.head`. A 301 to a different page silently breaks the link.

6. **Check for student data privacy (FERPA).** A previous term's export may contain student names in page bodies, filenames, and `<img alt>` attributes (Canvas copies the original filename into alt text). Run `python3 -m canvas_imscc.privacy "Course.imscc"` and `validate_package --names names.txt`. Flag it, never block it.

7. **Round-trip once after the first import of a new shape.** Export the course back out of Canvas, diff it against what you built. **Check the export's date first** — stale exports look identical. The round-trip is the only real test of what Canvas did, not just what you built.

## Quick Start Pattern

```bash
# Build the example course
python3 examples/build_example_course.py

# Validate
python3 -m canvas_imscc.validate_package "My Course.imscc"

# Accessibility audit
python3 -m canvas_imscc.accessibility "My Course.imscc"

# Privacy check
python3 -m canvas_imscc.privacy "My Course.imscc"
```

## Package Shape Reference

A `.imscc` is a zip with this structure:

```
imsmanifest.xml           the org chart: modules, items, resource declarations
wiki_content/*.html       one file per Canvas Wiki Page
web_resources/**          Course Files, folder structure preserved
course_settings/
  canvas_export.txt       REQUIRED, must be declared. Not checked for content.
  course_settings.xml     course title, defaults
  module_meta.xml         Canvas's module and item definitions
  context.xml             course name, canvas domain
  assignment_groups.xml   gradebook categories and weights
  rubrics.xml             gradeable rubrics
  files_meta.xml          optional
  media_tracks.xml        optional
<assignment-id>/         one folder per Assignment, at the ZIP ROOT
  <page>.html            the assignment description
  assignment_settings.xml points, grading type, submission type, group ref
```

## Common Gotchas

**Assignments became Pages** → The `course_settings` resource is undeclared (Rule 2). Check `imsmanifest.xml` for a resource with `href="course_settings/canvas_export.txt"` listing the settings files as `<file>` children.

**Everything is unclickable text** → The manifest is not well-formed XML (Rule 1). A malformed `imsmanifest.xml` imports with no error and renders every module item as inert text.

**A check passes but the thing is still wrong** → Diff against a real export. Reason about what Canvas "probably" keys on. A real export is the only authority, and the instructor can produce one in two minutes.

**Broken links after import** → Two causes:
- A stale `$IMS-CC-FILEBASE$`, `$CANVAS_OBJECT_REFERENCE$`, or `$CANVAS_COURSE_REFERENCE$` from a previous export. Check the source before assuming you caused it.
- A page-to-page link in the wrong format. The only form that works: `$WIKI_REFERENCE$/pages/<resource_id>`. Slugs (`/wiki_pages/...`) do not resolve. Anchors need `?titleize=0#` in front.

**External URL module items are missing** → An `ExternalUrl` item with no `<url>` in `module_meta.xml` imports silently as nothing. `validate_package` catches this.

**The Syllabus page is missing from the viewer** → The cartridge viewer does not render the Syllabus page. It imports correctly but shows nothing.

**Rubric does not arrive attached** → The rubric's `<rubric_identifierref>` must sit between `<workflow_state>` and `<assignment_overrides>` in `assignment_settings.xml`. Shipping a "RUBRIC" heading as text is not enough.

**Quiz has no questions** → Questions live in `non_cc_assessments/<id>.xml.qti`, NOT in `assessment_qti.xml`. Write them to the non-CC file. The CC file is an empty compatibility shell.

**New Quizzes do not import** → A different, LTI-based format. This kit only handles Classic Quizzes.

**Module items are dropped silently** → The page's `<meta name="identifier">` in its `<head>` must match the manifest resource `identifier`. A mismatch imports the page correctly but drops the module item.

## How to Ask the Instructor (Before Starting)

Ask one at a time. State sensible defaults rather than stalling:

1. Is there an export of a previous offering? (Decides Job A vs Job B)
2. What is the course title and code, as they should appear in Canvas?
3. Does the course use weighted assignment groups? (If yes, get categories and percentages — they must sum to 100)
4. Does anything need to be a real Assignment (points, due date, gradebook column, submission) rather than a Page?
5. What timezone is the course in? (Do due dates cross a DST boundary? Check. This is not obvious.)
6. Where do the source materials live, and are any of them large?

## When Something Goes Wrong

| Symptom in Canvas | Likely Cause | Fix |
|---|---|---|
| Assignments became Pages | `course_settings` undeclared (Rule 2) | Check imsmanifest.xml has the resource declaration |
| Everything unclickable | Malformed XML in `imsmanifest.xml` (Rule 1) | `validate_package` fails on parse errors first |
| A file link is broken | `$IMS-CC-FILEBASE$` relative to `web_resources/` | Percent-encode then XML-escape; Canvas's encoding is not `urllib.parse.quote` |
| "Missing links found" | A stale reference from a previous export | Check source before fixing |
| Rubric not attached | Rubric and assignment shipped separately | Ship them together via `rubric_id=` parameter |
| Quiz has no questions | Questions in CC file instead of non-CC file | Use `non_cc_assessments/<id>.xml.qti` |
| Module items dropped | Page `<meta identifier>` != manifest `identifier` | Use `builder.add_page_resource()` (writes the same id to both) |
| External URL items gone | Empty `<url>` tag in `module_meta.xml` | `validate_package` catches url-less items |

## Pitfalls

- **Rebuilding when an export exists.** A real export satisfies every structural requirement. Roll forward; do not rebuild.
- **Importing into a non-empty course.** Canvas duplicates everything. Always start from empty.
- **Using "All content" on import.** You must use "Select specific content" to verify Canvas's reading of the package.
- **Building the package from a dirty build directory.** `builder.py` overwrites rather than deletes, so a stale build leaves orphan files. The example clears the directory first.
- **Confusing `<content_type>` counts in `module_meta.xml` with assignment existence.** That file records module membership only. An assignment in no module shows as zero — but it can still be gradeable. Check for `<assignment_settings.xml>` with `<points_possible>`.
- **Assuming `quiz_type="practice_quiz"` needs an assignment group.** It does not. Only `quiz_type="assignment"` (the default) gets a gradebook column via nested `<assignment>` in `assessment_meta.xml`.
- **Writing inline `<style>` for visibility highlights.** Canvas strips ALL inline stylesheets on import. Use a real `<mark>` tag instead.
- **Not asking about student data.** A privacy check (`privacy.py` + `validate_package --names`) is report-only and never blocks a build, but it should be flagged.
