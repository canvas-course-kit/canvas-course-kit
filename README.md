# canvas-course-kit

Build a Canvas course — modules, pages, files, real gradebook-integrated
assignments, rubrics, due dates — **without API access**, by hand-building the
same `.imscc` export package Canvas itself produces, and importing it.

Then let an AI agent do the work. **If you use Claude Code**, install this as a
plugin and you get a `/canvas-build` command that walks you through it:

```
/plugin marketplace add canvas-course-kit/canvas-course-kit
/plugin install canvas-course-kit
```

Then type `/canvas-build`. The plugin also loads a background skill, so
just saying "help me get my syllabus into Canvas" is enough to trigger it.

**If you use anything else** — ChatGPT, Cursor, Copilot, the Claude web app —
clone the repo and hand [`AGENT.md`](AGENT.md) to your agent along with it. Same
instructions, no plugin machinery.

---

## Who this is for

Instructors whose institution has **disabled personal API access tokens**,
which closes off the obvious route of scripting a course through Canvas's REST
API. If you have API access, use the API — it is far simpler than any of this.

It is also useful if you are moving off Free-for-Teacher, rolling a course
forward semester to semester, or want your course content to live in version
control instead of only inside Canvas.

## Why it works

A **Course Export Package** is the exact zip format Canvas produces when you
export a course (Settings > Export Course Content). Importing one (Settings >
Import Course Content > "Canvas Course Export Package") is an ordinary
teacher-level action needing no admin permission.

So: build the file Canvas would have produced, and let Canvas's own importer
do the rest.

## Quick start

```bash
git clone <this repo>
cd canvas-course-kit

# Build the example course
python3 examples/build_example_course.py

# Check the result
python3 -m canvas_imscc.validate_package "/tmp/EXAMPLE 101.imscc"

# Check it for accessibility
python3 -m canvas_imscc.accessibility "/tmp/EXAMPLE 101.imscc"
```

Then upload the `.imscc` to
**<https://common-cartridge-viewer.netlify.app/>** — Instructure's own
open-source viewer, which runs locally in your browser — and look at the module
tree before importing anything. **But do not stop there.** See "Two previews,
and why you need both" below.

Requires Python 3.8+. No dependencies.

## Importing into Canvas

1. **Start from an EMPTY course shell.** This matters. Canvas never deletes on
   import, and importing over existing content has duplicated everything.
   Clearing a bad import means ticking a delete box on every item by hand, one
   at a time, with no bulk option.
2. Course **Settings > Import Course Content**.
3. Content Type: **Canvas Course Export Package**.
4. Choose the `.imscc`, and pick **"Select specific content"** rather than
   "All content". Import.
5. Canvas then pauses and asks you to choose what to bring in. **This screen is
   the most accurate preview you will get**, because it is Canvas's own
   importer telling you what it found. Expand the categories: if your
   assignments appear under Assignments you are fine, and if they appear only
   as Pages, stop and read rule 1 below before importing anything.
6. Select everything and continue. Large packages take a few minutes.

If you cannot get an empty shell, see the "targeted package" pattern in
[`docs/playbook.md`](docs/playbook.md): a package that declares no modules and
no pages will add resources to a live course without touching anything already
there.

## Two previews, and why you need both

The cartridge viewer and Canvas's own importer **can disagree**, and the
disagreement is the dangerous direction: a package has shown assignments
correctly in the viewer and then imported them into Canvas as Pages.

- The **cartridge viewer** reads the standard Common Cartridge parts, so it
  shows the module and item tree, indent levels and page bodies faithfully. Use
  it to check structure and content.
- **"Select specific content"** shows what *Canvas* thinks it has, which is the
  question that actually matters, because Canvas is the thing doing the import.
  Use it to check that Assignments are Assignments.

Neither one is optional, and neither one substitutes for the round-trip in
point 3 of "The three things most likely to bite you" below.

## What's here

| Path | What it is |
|---|---|
| [`AGENT.md`](AGENT.md) | **Hand this to your AI agent.** Instructions, rules, and the questions it should ask you first. |
| `skills/` | The same instructions packaged as a Claude Code plugin: `/canvas-build` plus an auto-triggering background skill. |
| [`docs/playbook.md`](docs/playbook.md) | The format, the workflow, and every gotcha, with the reasoning. Read this if you are doing it yourself. |
| [`docs/mutating-an-export.md`](docs/mutating-an-export.md) | Rolling a course forward from last term's export. Usually the right approach, and not the obvious one. |
| `canvas_imscc/builder.py` | The engine. Modules, pages, files, assignments, groups, rubrics, manifest writing, validation, zipping. |
| `canvas_imscc/rollforward.py` | Helpers for mutating an existing export: path encoding, due dates, rubric criteria, finding and removing things, streaming rewrites, diffing. |
| `canvas_imscc/validate_package.py` | Standalone checker. Runs against any `.imscc`, however it was made. |
| `canvas_imscc/accessibility.py` | Accessibility audit of every HTML body in a package, plus a read-only report on PDFs. See "Accessibility" below. |
| `examples/` | A complete, runnable course. Copy it and edit. |
| `tests/smoke_test.py` | Run this first in a new environment. Builds, validates, mutates and deliberately breaks a package to prove the checks fire. |

## Two approaches, and which to pick

**If a previous offering of the course exists in Canvas**, export it and
**mutate that export**. A real export already satisfies every structural
requirement, and it carries your assignments, rubrics, gradebook groups, files
and presentations through untouched at zero risk. A semester rollover usually
touches under 5% of a package. See
[`docs/mutating-an-export.md`](docs/mutating-an-export.md).

**Otherwise**, build from scratch with `builder.py`. See
[`examples/build_example_course.py`](examples/build_example_course.py).

## The three things most likely to bite you

1. **`course_settings/canvas_export.txt` must be *declared as a resource* in
   `imsmanifest.xml`, not merely present in the zip.** If it is not, Canvas
   silently uses the generic Common Cartridge importer: the modules look
   perfect, but every Assignment arrives as a **Page** with no points and no
   gradebook column, your weighted groups never arrive, and a copy of every
   page file is dumped into Files. The builder handles this. If you are
   hand-editing, do not disturb it.

2. **Parse the XML in the finished package.** A malformed `imsmanifest.xml`
   imports with no error message and renders every module item as inert,
   unclickable text. Regex checks all pass on such a file. This is the first
   thing `validate_package` does.

3. **A package that imports without errors is not a package that imported
   correctly.** After your first import of a new package shape, export the
   course back out of Canvas and diff it against what you built.

   **Check the export's date before you read anything into it.** Exports pile
   up in a folder and they all look alike. `validate_package` prints the
   newest entry timestamp for exactly this reason. A course has been declared
   broken on the evidence of an export that simply predated the import that
   fixed it.

   **The test for "did my assignments arrive as assignments" is whether
   `<hash>/assignment_settings.xml` files exist**, each with a
   `<points_possible>`. If Canvas turned them into Pages, those files are not
   in the export at all. Do **not** use the `<content_type>` counts in
   `course_settings/module_meta.xml` for this: that file records module
   *membership* and nothing else, so an assignment that exists, is gradeable,
   and simply is not linked from any module contributes no `Assignment` line.
   Reading that zero as "they all imported as Pages" is a mistake worth naming,
   because it looks like exactly the failure in rule 1 and is not.
   `validate_package` now reports both numbers so the difference is visible.

   The `<content_type>` counts are still the fastest way to see what is in your
   **modules**, which is what they describe.

## Accessibility

Institutions are pushing hard on Canvas accessibility scores, and the tools that
produce those scores (Ally, UDOIT) report a problem long after you have built
the course. This checks the package before you import it:

```bash
python3 -m canvas_imscc.accessibility "My Course.imscc"          # full report
python3 -m canvas_imscc.accessibility ./unzipped-export --strict  # exit 1 on errors
python3 -m canvas_imscc.validate_package "My Course.imscc" --a11y # both at once
```

It audits every HTML body in the package, **including the ones escaped inside
`<text texttype="text/html">` in discussions and announcements**, which is where
a checker that only opens `.html` files quietly misses an entire content type.

Findings are split in two, and the split is the point:

- **Errors** are machine-decidable failures: an `<img>` with no `alt`, a heading
  level skipped, `<h2>` to `<h4>`, a table with no `<th>`, an `<iframe>` with no
  `title`, link text that is only "click here", and text whose inline colour
  falls below the WCAG contrast ratio for its size.
- **Warnings** need a human: alt text that is vague or is really a filename,
  a bold paragraph standing in for a heading, a raw URL used as link text, a
  table with no caption or unscoped headers, and any embedded video, which needs
  captions no checker can verify.

**Accessibility findings do not fail your build.** `validate_package` reports a
one-line summary and leaves its exit status alone, because a missing `alt`
attribute is not a reason to block a package, and a validator that cries wolf is
one people learn to ignore. Once a course is clean, `--a11y-strict` (or
`--strict`) keeps it that way in CI.

### On alt text, and a trap specific to Canvas

Canvas copies a file's original filename into its `<img alt>` on import. That is
why real courses are full of alt text like `Screen%20Shot%202024-01-02.png`,
which passes any "does it have an alt attribute" check and tells a blind student
nothing. It is also how a student's name survives in a package long after the
file was renamed, which is why the same pattern is a privacy check in
`validate_package --names`. The audit reports filename-shaped alt text as an
error for both reasons.

### PDFs are reported, never rewritten

Untagged PDFs are usually the largest single component of a low Ally score, so
the audit inventories them: whether each has a structure tree, a document
language and a title. It does not modify them. Generating a real structure tree
is not something to fake, and writing `/MarkInfo /Marked true` without one makes
a file *claim* to be tagged, which turns some checkers green while a screen
reader still gets nothing out of it. Remediate PDFs in a tool built for it, ask
the publisher for an accessible copy, or replace them with HTML pages, which you
control completely.

### What this cannot tell you

An automated checker reaches roughly half of WCAG. It cannot judge whether alt
text is *accurate*, whether captions are correct rather than merely present,
whether colour is the only thing carrying a distinction, or whether the reading
order makes sense. **A clean report is a floor, not a pass.**

## Where this came from

Everything here was derived empirically — by reading real Canvas exports, and
by importing hand-built packages into a real Canvas instance and looking at
what actually happened. Official IMS and Canvas documentation was not
consulted. Every gotcha in the playbook is a bug that shipped at least once.

If Canvas changes its export format, re-derive from a fresh export rather than
assuming these notes stay valid forever. The method that matters is the one in
the playbook: **when a hand-built package behaves unlike a real export, diff
the manifests.** A real export is the only authority, and you can produce one
in two minutes.

## Reporting a Canvas behaviour that does not match these docs

Everything here was derived from one Canvas instance. Yours may differ by
version, by institutional configuration, or by being Free-for-Teacher rather
than institutional, and there is no way to know until someone says so.

**If an AI agent worked around a problem for you, ask it to write the report.**
It already knows what broke and what it changed, and otherwise the workaround
stays in your session and the bug stays in this repo forever. Open an issue with
the "Canvas behaved differently than documented" template, which asks for the
four things that matter: the symptom **in Canvas** rather than in the script,
whether you were building or mutating, what fixed it, and **whether
`validate_package` caught it or passed clean**. That last one is the most
valuable, because a validator that passes while the package is broken is a worse
problem than the original bug.

**Do not attach your `.imscc`, a chat transcript, or screenshots of a live
course.** A Canvas export contains student names in page bodies, in filenames,
and inside `<img alt>` attributes, because Canvas copies the original filename
into the alt text, so renaming the file does not remove the name. Three
sentences of symptom plus the fix is more useful than a long log anyway.

A pull request adding a row to the gotchas table (symptom, cause, fix) is the
single most useful thing you can send.

## License

MIT. See [LICENSE](LICENSE).

This project is not affiliated with or endorsed by Instructure.
