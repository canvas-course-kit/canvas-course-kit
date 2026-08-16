---
name: canvas-course-packaging
description: This skill should be used when the user wants to get course content into Canvas LMS without API access, mentions .imscc, Common Cartridge, "Canvas Course Export Package", importing or exporting a Canvas course, rolling a course forward to a new semester, or bulk-creating Canvas modules, pages, assignments, rubrics or due dates. Provides the builder library, the mutation helpers, and the rules that prevent silent import failures.
---

# Canvas course packaging

You are helping an instructor get content into a Canvas course without API
access. You will produce a `.imscc` file, a Canvas Course Export Package, which
the instructor imports by hand through Settings > Import Course Content. This is
an ordinary teacher-level action requiring no admin permission.

If the instructor **does** have a working Canvas API token, say so and use the
REST API instead. It is far simpler than any of this.

## Step 1: decide which of two jobs this is

**Job B: a previous term's version of this course already exists in Canvas.**
Ask the instructor to export it (Settings > Export Course Content > Course, then
download the `.imscc`) and **mutate that export** rather than rebuilding. Read
[`docs/mutating-an-export.md`](${CLAUDE_PLUGIN_ROOT}/docs/mutating-an-export.md).

**Job A: the course does not exist yet.** Build from source material with
`canvas_imscc/builder.py`. Read
[`docs/playbook.md`](${CLAUDE_PLUGIN_ROOT}/docs/playbook.md) first.

Job B is almost always right when a previous offering exists, and it is the
answer instructors do not expect. A real export already satisfies every
structural requirement and carries the assignments, rubrics, gradebook groups,
grading standard, files and presentations through untouched at zero risk. A
semester rollover usually touches under 5% of a package. Say so if the
instructor asks for a rebuild and an export is available.

## Step 2: ask these before writing anything

Guessing wastes a build cycle. Do not stall the whole build on a question you
can answer with a sensible default; state the assumption and keep going.

- Is there an export of a previous offering? (Decides Job A vs Job B.)
- Course title and code, as they should appear in Canvas.
- Weighted assignment groups? If yes, the categories and percentages, which must
  sum to 100.
- Does anything need to be a real **Assignment** (points, due date, gradebook
  column, submission) rather than a Page? They are different resource types and
  are not interchangeable.
- What timezone, and does the term cross a daylight-saving boundary? Due dates
  need this.
- Where do the source materials live, and are any of them large?

## The rules that cost real time when broken

The reasoning behind each is in
[`docs/playbook.md`](${CLAUDE_PLUGIN_ROOT}/docs/playbook.md).

1. **Parse the XML in the finished package before shipping it.** A malformed
   `imsmanifest.xml` imports with no error message and renders every module item
   as inert, unclickable text, because Canvas cannot build a resource map. Regex
   checks all pass on such a file.

2. **`course_settings/canvas_export.txt` must be DECLARED as a resource in
   `imsmanifest.xml`, not merely present in the zip.** Otherwise Canvas silently
   falls back to the generic Common Cartridge importer: modules look correct,
   but every Assignment arrives as a Page with no points and no gradebook
   column, weighted groups never arrive, and a copy of every page file is dumped
   into Files. `builder.py` handles this. In a real export it is already
   correct, so do not disturb it.

3. **`module_meta.xml` decorates the module tree; `<organizations>` IS the
   module tree.** Canvas builds modules from `<organizations>` in
   `imsmanifest.xml`. `course_settings/module_meta.xml` only adds
   `workflow_state`, `content_type` and `indent` to what is already there. A
   module or module item added to `module_meta` alone is not malformed and not
   dangling: it simply does not exist after import, silently. A whole module of
   assignments has gone missing this way. **Generate one from the other rather
   than editing both**, and note that for some items a real export sets
   `identifierref` in `module_meta` to the item's OWN identifier while
   `<organizations>` holds the true target, so regenerating naively destroys
   those links. `validate_package` now fails on any mismatch.

4. **Import into an EMPTY course shell.** Canvas never deletes on import.
   Clearing a bad import means the instructor ticking a delete box on every item
   by hand, one at a time, with no bulk option.

5. **Verify twice, in two places, because they can disagree.** See below.

6. **Never invent a URL from a pattern.** Fetch each external link and confirm
   it resolves *and still points at what you think it does*. A constructed
   museum-collection URL once 301'd to a different artist's page and a
   status-code check called it a pass.

7. **Check for personal data before shipping anything derived from a real
   course.** A previous term's export contains student names in page bodies, in
   filenames, and inside `<img alt>` attributes, because Canvas copies the
   original filename into the alt text. Renaming the file does not remove the
   name. Pass `--names` to the validator with names that must not appear.

8. **Decode references, do not guess how they are spelled.** Canvas writes one
   path several ways: `&quot;` inside a manifest href, and percent-encoding
   that leaves colons and commas literal (`Project%201:%20Notes/rock.gif`).
   Generating candidate spellings can only cover the encodings you thought of.
   `rollforward.remap_references()` parses each reference, decodes it, looks it
   up and re-emits it, so an unfamiliar spelling still matches and a path you
   are not moving is left untouched.

9. **When you change the shape of your data, check that your checker still sees
   it.** A validator whose regex quietly stops matching still prints a clean
   pass. Prefer parsing over pattern-matching, and make checks fail loudly
   rather than skip silently.

## Running the tools

The library lives at the plugin root, so set `PYTHONPATH`:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m canvas_imscc.validate_package "Course.imscc"
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m canvas_imscc.validate_package "Course.imscc" --names "Jane Doe" "John Roe"
```

Build scripts you write for the instructor should live in **their** project
directory, not in the plugin, and import the library the same way. Keep content
in a separate module from build logic: content changes far more often, and the
separation is what lets one source drive both the package and any spreadsheet or
handout you also generate, so they cannot drift.

## Verifying, which is not optional

First upload the `.imscc` to <https://common-cartridge-viewer.netlify.app/>,
Instructure's own open-source viewer, which runs locally in the browser and
renders the real module and item tree. Do not build your own preview; that was
tried and thrown away.

**Say this step out loud in your handoff, not only in a written checklist.** It
is the only point where the instructor reads the actual page and assignment
text before it lands in a live course, and it is the step most easily skipped
because the import feels like the "real" action. A checklist item they never
read is not a verification step.

**The viewer does not upload anything.** It is a client-side app: the cartridge
is parsed in the browser and never leaves the machine. Say so, because
instructors reasonably hesitate to drop a course package onto a random website,
and a package derived from a real course may still contain student data.

**If the hosted site is down, blocked by the institution, or the instructor
would rather not rely on it, it can be run locally.** The source is
<https://github.com/instructure/common-cartridge-viewer>, MIT licensed, so
keeping a copy is permitted:

```bash
git clone https://github.com/instructure/common-cartridge-viewer.git
cd common-cartridge-viewer
export NODE_OPTIONS=--openssl-legacy-provider   # needed on modern Node
npm ci && npm run build && npm start
```

A `docker compose build && docker compose up -d` path is bundled too, which
avoids the Node version problem entirely. A community fork exists at
<https://github.com/StrongMind/common-cartridge-viewer> if the upstream repo
ever disappears.

**The viewer complements your own checks, it does not replace them, and the
reverse is also true.** Parsing the package yourself catches structural faults
the viewer renders right past: unresolvable `$IMS-CC-FILEBASE$` links, manifest
hrefs with no matching zip entry, due dates on the wrong side of a DST
boundary. The viewer catches what parsing cannot: prose that reads wrong, a
heading that lost its emphasis, last term's dates still sitting in a body. Run
both, and do not let a clean validator tempt you into skipping the read.

Then tell the instructor to import with **"Select specific content"** rather
than "All content", so Canvas pauses and shows what *it* found before
committing.

**The two can diverge, and the divergence is the dangerous direction.** A
package has shown its assignments correctly in the cartridge viewer and then
imported them into Canvas as Pages. The viewer reads the standard Common
Cartridge parts; Canvas's importer is the thing whose opinion actually matters.
On the Select Content screen, assignments under Assignments means the package is
right. Assignments appearing only as Pages means rule 2 is broken. Stop and fix
it before importing.

After the **first** import of a new package shape, ask the instructor to export
the course back out and diff it against what you built. Nothing before this
point tells you what Canvas actually *did*. Compare the `<content_type>` counts
in `course_settings/module_meta.xml` first: that is where "11 Assignments"
arriving as "11 WikiPages" shows up in one line.

## Writing style for course content

Unless the instructor says otherwise, write in **their** voice, not yours. If
they have existing briefs, read two or three and copy their structure exactly.
Do not impose a template on a course that already has one.

Mark anything you generated that they have not read: set new assignments
`unpublished` and put a visible note at the top of draft pages using a real
`<mark>` tag, not a CSS class. **Canvas strips inline `<style>` blocks out of
every page on import**, so stylesheets are build-time decoration that will not
exist in the live course. Semantic tags and inline styles survive.

Do not write anything into a page that is only true at one point in time, unless
the page is explicitly a record. A classwork page written in past tense reads
wrong on every day before that class happens.

## Symptom index

| Symptom | Cause |
|---|---|
| Assignments imported as Pages | Rule 2, the `course_settings` resource declaration |
| Module items are unclickable text | Rule 1, malformed manifest |
| A file link is broken in the live course | `$IMS-CC-FILEBASE$` links are relative to `web_resources/`, percent-encoded then XML-escaped, and Canvas leaves commas literal unlike `urllib.parse.quote`. Use `rollforward.html_href()` |
| Something you changed did not change | You matched one spelling of a path. There are at least three. Use `rollforward.path_spellings()` |
| "Missing links found in imported content" | A stale `$CANVAS_OBJECT_REFERENCE$/modules/<id>` or `$CANVAS_COURSE_REFERENCE$/file_ref/<id>`. These survive course-to-course copies for years, so check the source export before assuming you caused it |
| A module or item you added never appears in Canvas | Rule 3. It went into `module_meta` but not `<organizations>` |
| A dangling link nobody's checker found | Discussion and announcement bodies are escaped HTML inside their own `.xml`, not `.html`. Scan every text entry |
| "assignment group weights sum to 0.0, not 100" on a valid course | Not an error. All-zero weights mean an unweighted, points-based gradebook |
| A file you moved still 404s, or the manifest became invalid XML | A spelling was missed, or a `"` in a filename was written literally into an href. Use `rollforward.remap_references()` and `xml_href()` |
| A check passes but the thing is still wrong | Diff against a real export. Do not reason about what Canvas "probably" keys on |

## If Canvas does something these docs do not describe

Say so out loud rather than silently routing around it. This kit was derived
from one Canvas instance, and a workaround you invent and do not report is a bug
that stays in the repo forever.

When you hit one, work around it, finish the instructor's job, and then **offer
to open an issue** at
<https://github.com/canvas-course-kit/canvas-course-kit/issues/new/choose>
using the "Canvas behaved differently than documented" template. Draft it
yourself; you already know what broke and what you changed. Report the symptom
**in Canvas** rather than in the script, whether this was a build or a mutation,
what fixed it, and **whether `validate_package` caught it or passed clean**.

Never paste the instructor's `.imscc`, your conversation, or a live course
screenshot into an issue, and strip student names, course IDs, instance URLs and
local paths from anything you do write. Ask the instructor before filing.

## Reference files

| File | Read it when |
|---|---|
| [`docs/playbook.md`](${CLAUDE_PLUGIN_ROOT}/docs/playbook.md) | Building from scratch, or you need the reasoning behind any rule above |
| [`docs/mutating-an-export.md`](${CLAUDE_PLUGIN_ROOT}/docs/mutating-an-export.md) | Rolling a course forward from last term's export |
| [`examples/build_example_course.py`](${CLAUDE_PLUGIN_ROOT}/examples/build_example_course.py) | You want a complete runnable build script to copy |
| [`canvas_imscc/builder.py`](${CLAUDE_PLUGIN_ROOT}/canvas_imscc/builder.py) | You need the exact API for modules, pages, files, assignments, groups, rubrics |
| [`canvas_imscc/rollforward.py`](${CLAUDE_PLUGIN_ROOT}/canvas_imscc/rollforward.py) | Path encoding, due dates, streaming rewrites, diffing two packages |
| [`tests/smoke_test.py`](${CLAUDE_PLUGIN_ROOT}/tests/smoke_test.py) | Verifying the toolchain works in a new environment |
