# Instructions for an AI agent building a Canvas course package

**Hand this file to your AI assistant along with the rest of this repository.**
It is written to be read by an agent, not by a person, though a person can
follow it too.

> **Using Claude Code?** You do not need this file. Install the repo as a plugin
> (`/plugin marketplace add misplacedfloridaman/canvas-course-kit`, then
> `/plugin install canvas-course-kit`) and use `/build-canvas-course`. The same
> content lives in `skills/`, wired up so paths resolve automatically. This file
> is the portable copy for every other agent.

You are helping an instructor get content into a Canvas course without API
access. You will produce a `.imscc` file, a Canvas Course Export Package,
which the instructor imports by hand.

---

## Before you write anything, decide which of two jobs this is

**Job A: the course does not exist yet, or is being built from source
material.** Use `canvas_imscc/builder.py`. Read `docs/playbook.md` first.

**Job B: a previous term's version of this course already exists in Canvas.**
Ask the instructor to export it (Settings > Export Course Content > Course,
then download the `.imscc`). Then **mutate that export** rather than
rebuilding. Read `docs/mutating-an-export.md`.

Job B is almost always the right answer when there is a previous offering,
and it is the answer instructors do not expect. A real export already
satisfies every structural requirement in the playbook and carries the
assignments, rubrics, gradebook groups, grading standard, files and
presentations through untouched at zero risk. Rebuilding them from scratch is
work you do not need to do and correctness you do not need to re-earn. Say so
if the instructor asks for a rebuild and an export is available.

---

## The rules that matter most

These are the ones that cost real time when broken. The reasoning is in
`docs/playbook.md`; the rules are here.

1. **Parse the XML in the finished package before shipping it.** Run
   `python3 -m canvas_imscc.validate_package your.imscc`. Its first check is
   that every `.xml` parses. A package with a malformed `imsmanifest.xml`
   imports without any error message and renders every module item as inert,
   unclickable text, because Canvas cannot build a resource map. Regex checks
   all pass on such a file.

2. **`course_settings/canvas_export.txt` must be DECLARED as a resource in
   `imsmanifest.xml`, not merely present in the zip.** If it is not, Canvas
   silently uses the generic Common Cartridge importer: modules look correct,
   but every Assignment arrives as a Page with no points and no gradebook
   column, the weighted assignment groups never arrive, and a copy of every
   page file is dumped into Files. `builder.py` does this for you. If you are
   mutating a real export, it is already correct — do not disturb it.

3. **Import into an EMPTY course shell.** Canvas never deletes on import, and
   re-importing over existing content has duplicated everything. Clearing a
   bad import means the instructor ticking a delete box on every item by hand,
   one at a time, with no bulk option. This is why verification before import
   matters more than it sounds like it should.

4. **Verify twice, in two different places, because they can disagree.**
   First at <https://common-cartridge-viewer.netlify.app/>, Instructure's own
   open-source viewer, which runs locally in the browser and renders the real
   module and item tree straight from the `.imscc`. Do not build your own
   preview; that was tried and thrown away. Then tell the instructor to import
   with **"Select specific content"** rather than "All content", so Canvas
   pauses and shows them what *it* found before committing.

   **The two can diverge, and the divergence is the dangerous direction.** A
   package has shown its assignments correctly in the cartridge viewer and then
   imported them into Canvas as Pages. The viewer reads the standard Common
   Cartridge parts; Canvas's importer is the thing whose opinion actually
   matters. On the Select Content screen, assignments appearing under
   Assignments means the package is right. Assignments appearing only as Pages
   means rule 2 is broken — stop and fix it before importing.

5. **Never invent a URL from a pattern.** If the course links to outside
   resources, fetch each one and confirm it resolves *and still points at what
   you think it does*. A constructed museum-collection URL once 301'd to a
   completely different artist's page; a status-code check called it a pass.

6. **Check for personal data before shipping anything derived from a real
   course.** A previous term's export contains student names in page bodies,
   in filenames, and inside `<img alt>` attributes, because Canvas copies the
   original filename into the alt text. Renaming the file does not remove the
   name. Pass `--names` to the validator with a list of names that must not
   appear anywhere.

7. **When you change the shape of your data, check that your checker still
   sees it.** A validator whose regex quietly stops matching still prints a
   clean pass. Prefer parsing over pattern-matching, and make checks fail
   loudly rather than skip silently.

---

## What to ask the instructor before starting

Ask these up front. Guessing wastes a build cycle.

- **Is there an export of a previous offering?** (Decides Job A vs Job B.)
- **What is the course title and code**, as they should appear in Canvas?
- **Does the course use weighted assignment groups?** If yes, get the
  categories and percentages; they must sum to 100.
- **Does anything need to be a real Assignment** (points, due date, gradebook
  column, submission) rather than a Page? Assignments and Pages are different
  resource types and are not interchangeable.
- **What timezone is the course in**, and does the term cross a
  daylight-saving boundary? You need this to write due dates correctly.
- **Where do the source materials live**, and are any of them large? Package
  size is rarely a problem — a real export's default course quota is 2 GB —
  but you should know before you start streaming gigabytes.

Ask one question at a time if the instructor prefers that. Do not stall the
whole build on a question you can answer with a sensible default; state the
assumption and keep going.

---

## Build loop

```
1. Draft content as clean HTML fragments. Markdown converted with Python's
   markdown library is fine as an intermediate:
       markdown.markdown(src, extensions=["extra", "sane_lists", "md_in_html"])
   md_in_html is required or markdown inside a raw HTML block renders as
   literal asterisks.

2. Write a build script that imports ImsccBuilder, defines the modules,
   pages, files and assignments, and calls write_manifest_and_settings().
   Keep CONTENT in a separate module from the BUILD LOGIC. You will edit
   content far more often than logic, and the separation is what lets one
   source drive both the package and any spreadsheet or handout you also
   generate, so they cannot drift.

3. b.validate() then b.zip_package(). Run both. The second is the one that
   catches a mismatch between the manifest and the ACTUAL zip entries rather
   than files that merely exist on disk.

4. python3 -m canvas_imscc.validate_package "Course.imscc"

5. Upload to common-cartridge-viewer.netlify.app and look at it.

6. Hand it to the instructor with the import instructions in README.md, and
   tell them to use "Select specific content" so they get Canvas's own reading
   of the package before it commits.

7. After the FIRST import of a new package shape, ask the instructor to
   export the course back out, and diff it against what you built. Nothing in
   steps 3-5 tells you what Canvas actually DID with the package. Compare the
   <content_type> counts in course_settings/module_meta.xml first: that is
   where "11 Assignments" showing up as "11 WikiPages" becomes visible in a
   single line.
```

---

## Writing style for course content

Unless the instructor says otherwise:

- **Write in the instructor's voice, not yours.** If they have existing
  briefs, read two or three and copy their structure exactly — headings,
  order, level of detail. Do not impose a template on a course that already
  has one.
- **Mark anything you generated that they have not read.** Set new
  assignments `unpublished` in the package, and put a visible note at the top
  of draft pages. Use a real `<mark>` tag, not a CSS class: **Canvas strips
  inline `<style>` blocks out of every page on import**, so any styling you
  write is build-time decoration that will not exist in the live course.
  Semantic tags and inline styles survive; stylesheets do not.
- **Do not write anything into a page that is only true at one point in
  time**, unless the page is explicitly a record. A classwork page written in
  past tense reads wrong on every day before that class happens.

---

## When something goes wrong

**The package imports but Assignments became Pages.** Rule 2. Check that the
manifest declares the `course_settings` resource.

**Everything in the modules is unclickable text.** The manifest is not
well-formed XML. Rule 1.

**A file link is broken in the live course.** `$IMS-CC-FILEBASE$` links are
relative to `web_resources/`, are percent-encoded and then XML-escaped, and
Canvas's percent-encoding is not `urllib.parse.quote`'s — it leaves commas
literal. Use `rollforward.html_href()`.

**Something you changed did not change.** You matched one spelling of a path.
There are at least three. Use `rollforward.path_spellings()`.

**Canvas reports "Missing links found in imported content".** A page body
contains a `$CANVAS_OBJECT_REFERENCE$/modules/<id>` or
`$CANVAS_COURSE_REFERENCE$/file_ref/<id>` pointing at something not in the
package. These are Canvas's placeholders for "a module in this course" and "a
file in this course", and they survive being copied from course to course for
years, so a stale one is usually inherited rather than introduced. Check the
source export before assuming you caused it. `validate_package` checks these.

**A check passes but the thing is still wrong.** Diff against a real export.
Do not reason about what Canvas "probably" keys on. A real export is the only
authority, and the instructor can produce one in two minutes.
