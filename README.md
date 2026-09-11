# Canvas Course Kit

Build a Canvas course — modules, pages, files, real gradebook-integrated
assignments, rubrics, due dates — **without API access**, by hand-building the
same `.imscc` export package Canvas itself produces, and importing it.

## What it does

- **Builds a real Canvas course from a folder of your own material** — modules,
  pages, files, assignments with points and due dates, weighted gradebook
  groups, rubrics, the Syllabus page, and working page-to-page links including
  deep links to an anchor — and packages it as a file you import yourself, no
  admin involved.
- **Rolls a course forward** from last term's export, usually touching under 5%
  of the package and carrying everything else through untouched.
- **Catches the import failures that are silent**, the ones where Canvas reports
  success and quietly turns every assignment into a page with no gradebook
  column. Each check exists because that mistake shipped at least once.
- **Audits accessibility before students see it**, rather than after Ally or
  UDOIT scores it: alt text, heading order, table headers, link text, contrast,
  and a read-only report on untagged PDFs.
  See [Accessibility](#accessibility).
- **Flags anything that looks like student data** before you hand a package to
  a colleague. See [What about FERPA?](#what-about-ferpa)
- **Puts your course in version control**, as text you can diff, instead of only
  inside Canvas.

Nothing here needs a Canvas API token, an admin, or a paid tool. Python 3.8+,
no dependencies.

---

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

**Never used GitHub before?** You do not need to. Download
**[the whole kit as a zip file](https://github.com/canvas-course-kit/canvas-course-kit/archive/refs/heads/main.zip)**
and unzip it. That is what "clone the repo" means, and the zip is the same
files.

The simplest way to use it from there, if you work with an AI coding assistant:
put the unzipped folder next to your course materials, in one folder, and point
the assistant at that folder. It will find the kit, read the skills in
`skills/`, and take it from there. You do not have to run any of the commands
below yourself.

If you would rather drive it yourself:

```bash
git clone https://github.com/canvas-course-kit/canvas-course-kit.git
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
there. Note its limit, which is documented there: **a targeted package can add
to a live course but cannot update it.** Reusing an existing item's identifier
does not make Canvas overwrite it — a page and an assignment were both tested,
and both imported as duplicates. To change one or two existing items, edit them
in Canvas.

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
| `canvas_imscc/privacy.py` | Flags possible student data. Report only: never modifies, never blocks. See "What about FERPA?" below. |
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

## What about FERPA?

**This kit does not perform a FERPA compliance check, and nothing automated
can.** Compliance is a legal determination about your institution and your
records, not something a script decides. What follows is the factual shape of
the problem so you can make that call yourself.

**A Canvas *Course* export contains no student records.** Checked against a real
export of a course that had actually run: there are no submissions, no
gradebook, no enrollments, no user accounts, no discussion posts. The only
user-shaped things in the package are assignment *settings* like
`submission_types` and `grader_count`, which describe configuration rather than
people. Canvas exports student data through a different mechanism entirely, so
the surface here is far smaller than it first appears.

**What does leak is student identity embedded incidentally in content**, and it
survives in three places that are easy to miss:

- A page body that names a student ("nice solution from …").
- A **filename** in `web_resources/`, because student work gets uploaded as an
  example and keeps the name it arrived with.
- An **`<img alt>` attribute**, because Canvas copies a file's original filename
  into the alt text on import. Renaming the file afterwards does not remove the
  name from the alt text.

`validate_package --names names.txt` sweeps all three, entry names as well as
file contents. **Its limit is that you have to know the names already.** It
finds names you give it; it does not discover them.

### The sweep that does not need a list

```bash
python3 -m canvas_imscc.privacy "My Course.imscc"
```

This flags the places student identity actually hides, without being told any
names. It **never modifies the package and never fails a build.** It always
exits 0. A privacy warning is a prompt to look, and a checker that blocks over a
false positive is one people switch off.

Findings come in two levels, and the split is doing real work:

- **review** — something that should not be in a Course export at all: a
  `submissions/` path, a gradebook or roster spreadsheet, XML describing people
  rather than settings, or alt text carrying a name plus an upload timestamp,
  which is how Canvas names a file uploaded from the Student app.
- **look** — a real pattern with real false positives. Your own email address
  will match. You will recognise it in a second, which is the point.

It deliberately does **not** try to guess whether a string is a person's name.
Every art history page is full of them, and a report that cries wolf is one
nobody reads. It looks for *shapes* instead: submission naming conventions,
Canvas's own upload filenames, paths that do not belong.

That narrowness is the reason it works. Run against a real course that had
already been taught, it produced one **review** line out of twenty-three
findings, and that one line was a student's name sitting in an `<img alt>`
attribute, four years after the file itself had been renamed.

**None of this is a compliance check.** A clean report means the automated
patterns found nothing, not that the package is safe to distribute. If you are
sharing a package outside your institution, read `web_resources/` yourself.

Being untagged is separate from being private. The accessibility audit's PDF
report says nothing about whether a PDF contains student work.

## Where this came from

Everything here was derived empirically — by reading real Canvas exports, and
by importing hand-built packages into a real Canvas instance and looking at
what actually happened. Every gotcha in the playbook is a bug that shipped at
least once.

The empirical method still comes first, because it is the only thing that tells
you what your Canvas actually does. But documentation does exist and is worth
reading once you know what to look for; see **Related work** below for where it
is and what each source settles.

If Canvas changes its export format, re-derive from a fresh export rather than
assuming these notes stay valid forever. The method that matters is the one in
the playbook: **when a hand-built package behaves unlike a real export, diff
the manifests.** A real export is the only authority, and you can produce one
in two minutes.

## Related work

**[brockcraft/canvas-imscc](https://github.com/brockcraft/canvas-imscc)** (MIT)
is a Claude skill for reading and building `.imscc` files, from a
course-cartridge project at the University of Washington. It overlaps this kit
and is worth reading: it is short, and its two reference files cover extraction
and reconstruction in one pass.

It contributed a fix here. It states that Canvas resource identifiers must be
`g` plus 32 hex characters and that human-readable ids fail silently, which
caught a hand-written identifier in a package this kit had already validated as
clean.

Two of its claims did not survive testing, recorded here so nobody re-tests
them:

| Claim | What we found |
|---|---|
| ZIP entries must use `ZIP_STORED`; `ZIP_DEFLATED` fails silently | Three real Canvas exports are predominantly **deflated** (one is 198 deflated entries and zero stored). Packages from this kit are fully deflated and import fine |
| Rubrics in `rubrics.xml` reach the rubric bank but are **not** attached to assignments, so attachment must be done by hand afterwards | `<rubric_identifierref>` inside `assignment_settings.xml` is the attachment mechanism, and it travels in the package. Confirmed by importing 13 assignments built this way: **the rubrics arrived attached** |

Neither is a criticism. Both are the failure mode described just above — a
conclusion drawn from one instance and one set of failures. Ours are too.
**Diff against a real export before believing any of us.**

The `$WIKI_REFERENCE$` link format documented here went the same way. It was
read out of canvas-lms source first, then **confirmed by live import on
2026-09-10**: a 61-page package carrying 208 page-to-page links, deep links
into a glossary, 13 assignments with attached rubrics, weighted groups and a
Syllabus page imported with **zero errors**, every anchor jumping correctly.
That is the standard anything in this README is supposed to meet.

**[jasp-nerd/courseforge](https://github.com/jasp-nerd/courseforge)**
(Apache-2.0) is a TypeScript monorepo that solves the opposite half of this
problem. It generates a cartridge and then pushes it through Canvas's
`content_migrations` API, wrapped in an MCP server, so one call builds a whole
course. If you have a working Canvas API token, that is the easier road and you
should take it. This kit exists for institutions that have turned personal
access tokens off, where the hand-import is the only way in.

It is worth reading anyway. Its `docs/imscc-format.md` covers the same ground as
this README and agrees with it, and it does two things this kit does not: real
QTI 1.2 quiz generation for eight question types, and discussions and
announcements. It is also the source of the orphan-file check below. Two gaps
to know about if you go that way: rubrics are an empty stub in its builder and
still on its roadmap, and it does not set `group_weighting_scheme`, so weighted
gradebooks import and are silently ignored — the same bug this kit shipped
until it was caught.

It contributed a check here. Its validator asks whether every file **in the
zip** is declared by some resource, which is the direction this kit's validator
was missing: check 3 asked only whether every declared file exists. A package
built into a dirty build directory once shipped 193 entries against 79
resources, and every check passed, because `add_page_resource()` renames rather
than overwrites and `zip_package()` zips the whole folder. Those orphans import
into Files as content nobody asked for. That check is now check 3b.

### Testing against real cartridges

CourseForge also pointed the way to
**[commonsyllabi/commoncartridge](https://github.com/commonsyllabi/commoncartridge)**
(MIT), a parser project whose test corpus collects public course exports from
Canvas, Moodle, Blackboard, Brightspace and Sakai. Running this kit's validator
across eight of them found four checks that failed correct packages:

| Check | What it did | What it does now |
|---|---|---|
| `course_settings` files listed in their resource | Failed every real Canvas export, twice: once on the bare `course_settings/` directory entry, once on `media_tracks.xml`, which real exports ship undeclared | A note. Only the `canvas_export.txt` declaration decides anything |
| Group weights sum to 100 | Failed a real export whose weights were stale leftovers in an unweighted course | Only binds when `group_weighting_scheme` is `percent`. Weights summing to 100 **without** it is now its own failure, because that is the silent-wrong-grades bug |
| Empty directory entries | Failed real Canvas exports, which ship an empty `non_cc_assessments/` | A failure only under `web_resources/`, where Canvas turns it into an empty Files folder a student can click. Cosmetic elsewhere |

None of these were subtle, and none of them were visible without real packages
to run against. A validator that fails correct work gets switched off, which
costs more than the checks were worth. If you extend this kit, run it across
that corpus before you trust a new check.

### Where the documentation is

- **[canvas-lms](https://github.com/instructure/canvas-lms) itself** is the only
  place the Canvas-specific half is documented at all, because
  `course_settings/*.xml`, rubrics, `assignment_settings` and
  `group_weighting_scheme` are Canvas extensions that appear in no published
  standard. `lib/cc/cc_helper.rb` defines the reference tokens and every URL
  form Canvas emits. `lib/user_content.rb` holds the `UriMatch` parsing that
  decides what survives a rewrite. And
  `spec/lib/canvas_imported_html_converter_spec.rb` documents what the
  **importer** accepts, as executable examples — the closest thing to a
  specification that exists.
- **The [Common Cartridge v1.1 Implementation profile](https://www.imsglobal.org/cc/ccv1p1/imscc_profilev1p1-Implementation.html)**
  covers the container rather than the Canvas payload, but it is where the hard
  constraints live: one organization, rooted on a single **untitled** item
  container, resources identified with GUIDs, and only Learner Experience
  resource types in the organization hierarchy.
- **The Canvas REST API docs are not useful for this.** They describe live
  objects, not the export format, and are silent on the fields that decide
  whether an import succeeds.

## What this kit does not do

Not limitations of the format, just of this kit. Each is a package Canvas would
accept if it were built.

- **Quizzes and question banks.** QTI is a separate format inside the cartridge
  and nothing here writes it.
- **LTI tools, discussions, announcements, and peer review.**
  ([courseforge](https://github.com/jasp-nerd/courseforge) writes discussions
  and announcements, if you need them.)
- **Per-section differentiation.** `assignment_overrides` is how one course
  gives two sections different due dates. Not implemented.

And one thing no package can do, which matters more than any of the above:
**Canvas cannot update an existing page or assignment on import.** It only
adds. A second import of the same package duplicates everything, and undoing it
is one checkbox at a time.

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
