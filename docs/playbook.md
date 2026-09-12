# Playbook: building Canvas course content without API access

How to get real content — modules, pages, files, gradebook-integrated
assignments, rubrics — into a Canvas course when your institution has disabled
personal API access tokens.

Everything here was derived empirically, by reading real Canvas exports and by
importing hand-built packages into a real Canvas instance and looking at what
happened. Official IMS and Canvas documentation was not consulted. Treat this
document as the source of truth, and if Canvas changes its export format,
re-derive from a fresh export rather than assuming this stays valid forever.

## Why this approach and not the API

Canvas has a REST API that would make all of this trivial: create module,
create page, upload file, one call each. Many institutions disable personal
access token creation, which closes that route for ordinary instructors.

A Course Export Package is the workaround. It is the exact zip format Canvas
produces when a teacher exports a course (Settings > Export Course Content),
and importing one (Settings > Import Course Content > "Canvas Course Export
Package") is an ordinary teacher-level action needing no admin permission. So
you hand-build the file Canvas would have produced and let Canvas's own
importer do the rest.

## Format overview

A `.imscc` is a zip with this shape:

```
imsmanifest.xml           the org chart: modules, items, resource declarations
wiki_content/*.html       one file per Canvas Page
web_resources/**          Course Files, folder structure preserved exactly
course_settings/
  canvas_export.txt       REQUIRED, and must be declared. See below.
  course_settings.xml     course title, defaults
  module_meta.xml         Canvas's own module and item definitions
  context.xml             course name, canvas domain, root account name
  assignment_groups.xml   gradebook categories and their weights
  rubrics.xml             gradeable rubrics
  files_meta.xml          optional; real exports carry it
  media_tracks.xml        optional; real exports carry it
<assignment-id>/          one folder per Assignment, at the ZIP ROOT
  <page>.html             the assignment description
  assignment_settings.xml points, grading type, submission type, group ref
```

**`imsmanifest.xml`** is the standard IMS Common Cartridge manifest.
`<organizations><organization structure="rooted-hierarchy"><item
identifier="LearningModules">` contains one `<item>` per Canvas Module. Nested
`<item>`s become module items if they carry an `identifierref` pointing at a
`<resource>`, or plain text dividers if they do not. The `<resources>` section
separately declares every Page and File.

**`course_settings/module_meta.xml`** is Canvas-specific and is what actually
drives the Modules UI on import. Each `<module>` has a `<position>`; each
`<item>` has a `content_type` (`WikiPage`, `Attachment`, `Assignment`,
`ContextModuleSubHeader`, `DiscussionTopic`, `ExternalUrl`), a `<position>`,
and an `<indent>` from 0 to 5.

**Canvas Modules do not nest.** There is no parent/child module relationship
anywhere in this schema. The `indent` level on items is how you fake a
sub-module: one top-level module per topic, its contents as indented items
underneath a `ContextModuleSubHeader` divider.

---

## The one thing that breaks everything

**The course-settings resource must be DECLARED in the manifest.** Canvas
treats a package as a *Canvas Course Export Package* only if
`imsmanifest.xml` declares a resource whose `href` is
`course_settings/canvas_export.txt`, listing the settings files as `<file>`
children:

```xml
<resource identifier="gXXXX"
          type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
          href="course_settings/canvas_export.txt">
  <file href="course_settings/course_settings.xml"/>
  <file href="course_settings/module_meta.xml"/>
  <file href="course_settings/assignment_groups.xml"/>
  <file href="course_settings/rubrics.xml"/>
  <file href="course_settings/files_meta.xml"/>
  <file href="course_settings/context.xml"/>
  <file href="course_settings/media_tracks.xml"/>
  <file href="course_settings/canvas_export.txt"/>
</resource>
```

**Putting the files in the zip is not enough.** Undeclared, Canvas never opens
`course_settings/` at all, so `module_meta.xml`, `assignment_groups.xml`,
`rubrics.xml` and every `assignment_settings.xml` are ignored.

This fails **silently**. The import reports no errors and the modules look
right, because modules ride on `<organizations>`, which is standard Common
Cartridge. What you get instead is the generic Common Cartridge importer,
which:

- builds modules, subheaders and pages from the manifest, so the import
  **looks completely correct**;
- ignores `assignment_settings.xml` and `assignment_groups.xml`, so every
  Assignment lands as a **Page** with no points, no gradebook column and no
  submission type, and the weighted groups never arrive;
- dumps the unrecognised assignment folders, plus **a copy of every
  `wiki_content` HTML file**, into Files as junk.

This was found only after a course had been live for a day, by exporting it
back out of Canvas and diffing: 11 assignments had become pages, five weighted
groups were gone, 125 stray files were sitting in Files. The
`assignment_settings.xml` files had been correct the whole time. They were
simply never read.

Two wrong guesses preceded the right answer, recorded so nobody repeats them.
First: that the package was missing `canvas_export.txt` entirely, so adding the
file would fix it. It did not; the file shipped and the package still imported
as plain Common Cartridge. The answer came only from diffing the hand-built
manifest against a real export's manifest and noticing that the real one
declares `course_settings` as a resource.

**The lesson, worth more than the fix: when a hand-built package behaves
unlike a real export, diff the manifests. Do not reason about what Canvas
"probably" keys on.** A real export is right there and is the only authority.

**And the corollary: a package that imports without errors is not a package
that imported correctly.** The only real verification is to export the course
back out of Canvas and diff it against what you built. Do that once after the
first import of any new package shape.

Canvas's own exports put a joke in `canvas_export.txt`. The content is not
checked, only presence.

---

## Workflow

1. **Draft page bodies as clean HTML.** Markdown converted with Python's
   `markdown` library is a fine intermediate:
   `extensions=["extra", "sane_lists", "md_in_html"]`. The last is required or
   markdown inside a raw HTML block renders as literal asterisks. Do not
   maintain parallel `.md`, `.docx` and `.html` copies of the same content;
   that is overhead with no payoff once Canvas is the target.

2. **Separate content from build logic.** Put the course's text in its own
   module and the assembly in another. You will edit content constantly and
   logic rarely, and the separation is what lets one source drive both the
   package and any spreadsheet or handout you also generate, so the two cannot
   drift apart.

3. **Write a build script** that imports `ImsccBuilder`, defines the modules,
   pages, files and assignments, and calls `write_manifest_and_settings()`.

4. **Validate, then zip, then validate the zip.** `b.validate()` checks the
   build directory. `b.zip_package()` checks that every resource `href` matches
   an actual entry *inside the zip*, which is the check that catches a
   path-encoding bug instead of letting it reach an import. Then run
   `python3 -m canvas_imscc.validate_package` on the finished file.

5. **Verify at <https://common-cartridge-viewer.netlify.app/>.** Instructure's
   own open-source viewer, running locally in the browser. It renders the real
   module and item tree, indent levels included, straight from the `.imscc`.
   This matters more than it sounds like it should, because fixing a bad import
   means ticking a delete box on every single item in Canvas's UI by hand, one
   at a time, with no bulk option.

6. **Import into an empty shell, using "Select specific content".** Canvas then
   pauses and shows you what it found before committing, which is a second and
   better preview: it is the importer's own reading of the package rather than
   a third-party parser's.

   **The two previews can disagree.** A package has shown its assignments
   correctly in the cartridge viewer and then imported them into Canvas as
   Pages. The viewer reads the standard Common Cartridge parts faithfully, so
   it is right about structure and content; Canvas's importer is the thing
   whose opinion decides what you actually get. Use the viewer to check the
   module tree, and Select Content to check that Assignments are Assignments.

   Re-importing over a non-empty course has duplicated everything. Canvas never
   deletes on import.

7. **Round-trip once.** After the first import of a new package shape, export
   the course back out and diff.

   **Check the export's date first.** Exports accumulate and look alike;
   `validate_package` prints the newest entry timestamp so you can tell whether
   you are reading the course's current state or last month's.

   **To ask whether assignments arrived as assignments, look for
   `<hash>/assignment_settings.xml` with a `<points_possible>`.** If Canvas
   made them Pages, those files do not exist in the export. Do NOT read this
   off the `<content_type>` counts in `module_meta.xml`: that file records
   module membership only, so an assignment that exists and is gradeable but
   sits in no module shows up as zero there. That zero looks exactly like the
   rule-2 failure and is not it.

   ```
   unzip -q -o fresh-export.imscc -x 'web_resources/*' -d canvas/
   unzip -q -o 'Your Package.imscc' -x 'web_resources/*' -d built/
   ```

   Round-tripping is also the only safe way to reconcile drift. If the
   instructor edits pages inside Canvas, a rebuild silently overwrites those
   edits; exporting first recovers them.

---

## Pattern: real Assignments, not Pages

A Canvas Assignment is a materially different resource type from a Page.

`add_assignment_group(title, weight)` once per grading category, then
`add_assignment_resource(title, body_html, group_id, points_possible=100.0,
submission_types="on_paper")` per assignment. Use `"online_upload"` for
anything turned in digitally, `"on_paper"` for work handed in physically or
reviewed in person, `"none"` for a gradebook line with no submission.

Under the hood: an Assignment lives in its own folder named by resource id at
the package **root**, not under `wiki_content/`, containing the description
HTML plus `assignment_settings.xml`. Its manifest `<resource>` uses
`type="associatedcontent/imscc_xmlv1p1/learning-application-resource"`, not
`"webcontent"`. Groups are declared once in `assignment_groups.xml` and
referenced by `assignment_group_identifierref`.

Group weights must sum to 100 if you use weighting at all.

## Pattern: real rubrics

A "RUBRIC" heading in an assignment description is just text. A gradeable
Canvas Rubric is `course_settings/rubrics.xml` plus a `<rubric_identifierref>`
block in the assignment's `assignment_settings.xml`, sitting between
`<workflow_state>` and `<assignment_overrides>`.

Keep both. The text is what a student reads inside the assignment; the rubric
is what the instructor grades with.

Each rating is keyed to its criterion by `criterion_id` and needs its own
`<id>`. Real exports use opaque strings, so any stable unique value works.

**A rubric's criteria must sum to its own `points_possible`, and each rating
scale must top out at its criterion's points.** Canvas imports one that does
not without a word, and the arithmetic appears nowhere until someone grades
with it. If you are *editing* an existing rubric rather than building one, use
`rollforward.rewrite_rubric()`; the two ways a hand-rolled rewrite goes wrong
are in [`mutating-an-export.md`](mutating-an-export.md).

## Pattern: page-to-page links

Linking one page to another is the part of this format most likely to look
right, validate clean, pass the cartridge viewer, and then produce dozens of
errors on import. One package produced **54** of them, every one reported only
as the unhelpful "Missing links found in imported content - Wiki Page body",
with each live link landing on "page not found".

The form Canvas resolves is:

```
$WIKI_REFERENCE$/pages/<RESOURCE IDENTIFIER>
```

The target is the page's `identifier` in `imsmanifest.xml`. Not a URL slug, not
the page title, and **not** `$WIKI_REFERENCE$/wiki_pages/<anything>` —
`wiki_pages` is the ActiveRecord model name, not a route, and it does not
resolve.

A fragment needs a query string in front of it:

| Written | What Canvas does |
|---|---|
| `/pages/<id>` | opens the page |
| `/pages/<id>#anchor` | **breaks.** The fragment is absorbed into the identifier, Canvas finds no page, and offers to create one |
| `/pages/<id>?titleize=0#anchor` | opens the page **and** jumps to the anchor |

The cause is in canvas-lms: `UriMatch#query` is `rest[/\?.*/]`, so `?` is what
terminates the object id. Read from source, then **confirmed by live import
(2026-09-10): a 61-page package with 208 page links and deep links into a
glossary imported with zero errors and every anchor jumping correctly.**

Use `builder.page_link(page_title)`, which handles all of this:

```python
rid = b.add_page_resource("Aquatint", body)
# and anywhere, including in a page written BEFORE its target exists:
body = 'See <a href="%s">Aquatint</a>.' % b.page_link("Aquatint")
body = 'See <a href="%s">the grain</a>.' % b.page_link("Aquatint", anchor="grain")
```

Resource ids do not exist until the page is added, so `page_link()` writes a
placeholder and `write_manifest_and_settings()` resolves them once every page
exists. A link naming a page that was never added fails the build.
`validate_package` rejects both broken forms independently.

One consequence worth knowing: **Canvas derives a page's URL from its title.**
Two pages sharing a title collide in the live course and no link can tell them
apart, so `add_page_resource()` refuses the second one.

## Pattern: the Syllabus page

Canvas has one built-in Syllabus per course. It is not a Page and not a module
item: a real export carries it as `course_settings/syllabus.html`, declared in
its **own** resource with `intendeduse="syllabus"`, and deliberately left out
of the main `course_settings` resource's file list.

```python
b.add_syllabus("<p>Everything a student needs in week one.</p>")
```

Before hunting for a bug: **the Common Cartridge viewer does not render the
Syllabus page**, so a correct package looks like it is missing one until you
actually import it.

## Pattern: quizzes

A Canvas Classic Quiz is **four** pieces, and the shape is not what you would
guess:

| Path | What it holds |
|---|---|
| `<rid>/assessment_qti.xml` | Common Cartridge profile. Its `<section>` is **empty** |
| `non_cc_assessments/<rid>.xml.qti` | Canvas's own QTI. **The questions live here** |
| `<rid>/assessment_meta.xml` | Title, points, quiz type, attempts, assignment group |
| `imsmanifest.xml` | **Two** resources joined by a `<dependency>` element |

**The CC file is a compatibility shell with no questions in it.** Three real
exports agree: Michael Diaz's University of Tampa export (0 items in the CC
file, 3 in the non-CC one) and both corpus exports. Write the questions into
the CC file and Canvas imports a quiz with no questions and reports no error.
(courseforge does it the other way round and may also import; this kit follows
what Canvas itself produces.)

**Confirmed by a live import, 2026-09-12.** A package built exactly as below —
five questions, one of each supported type, 13 points, shipped unpublished —
imported into a real Canvas course with the questions, the answer keys and the
gradebook column all intact. Everything above is now tested behaviour rather
than inference from exports.

```python
from canvas_imscc.quiz import (multiple_choice, true_false, essay,
                               short_answer, multiple_answers)

g = b.add_assignment_group("Quizzes", 20.0)
qid = b.add_quiz("Studio Safety", [
    multiple_choice("<p>Which acid bites copper?</p>",
                    [("<p>Ferric chloride</p>", True), ("<p>Water</p>", False)], points=2),
    true_false("<p>Hard ground resists acid.</p>", True),
    essay("<p>Describe your plate preparation.</p>", points=5),
    short_answer("<p>The tool that scrapes a burr is a _____.</p>",
                 ["burnisher", "Burnisher"]),
    multiple_answers("<p>Select every intaglio process.</p>",
                     [("<p>Etching</p>", True), ("<p>Drypoint</p>", True),
                      ("<p>Lithography</p>", False)], points=3),
], assignment_group_id=g)
b.add_item(mod, "Quizzes::Quiz", "Studio Safety", resource_id=qid)
```

Points default to the sum of the questions. A **graded** quiz
(`quiz_type="assignment"`, the default) needs an assignment group exactly as an
assignment does, and gets a nested `<assignment>` block inside
`assessment_meta.xml` carrying `submission_types=online_quiz`; that block is
what gives it a gradebook column. `quiz_type="practice_quiz"` needs no group.

Answer matching is worth knowing: `short_answer` compares **case-sensitively**,
as separate `<varequal>` entries, which is why the real exports list both
`Programmers` and `programmers`. `multiple_answers` is scored all-or-nothing,
every correct box ticked and every wrong one clear, expressed as one `<and>`
with a `<not>` around each wrong choice.

**Three things this does not cover.** **Question banks** appear in no export
here in a form worth copying; where they exist, the questions sit in extra
`non_cc_assessments/*.xml.qti` files belonging to no declared quiz, and
`validate_package` reports them rather than pretending to understand them.
**New Quizzes** are a different, LTI-based thing entirely, and nothing here
builds them. And **the remaining six question types** (matching,
numerical, fill-in-multiple-blanks, multiple dropdowns, file upload, text only)
are present in the corpus but not implemented.

### Getting a quiz OUT of Canvas

Three routes, observed on a University of Tampa course on 2026-09-12, and they
do not behave the same:

| Route | Result |
|---|---|
| Settings > Export Course Content > **Quiz** | Manifest with an **empty `<resources>`**, twice. Quiz was unpublished at the time |
| Settings > Export Course Content > **Course** | The quiz, complete |
| **New Quizzes Build menu > Export** | The quiz, complete, and the cleanest form of it |

**The New Quizzes Build-menu export is worth knowing about.** It yields a tiny
three-file package — manifest, `<id>/<id>.xml`, `<id>/assessment_meta.xml` —
whose QTI is **byte-identical** (apart from resource ids) to what a full course
export writes into `non_cc_assessments/<id>.xml.qti`. Its manifest uses
`type="imsqti_xmlv1p2"` paired to the meta resource by `<dependency>`, the same
two-resource shape described above. If you want to read real question XML
without unpacking a 140 MB course export, this is the way.

**A quiz authored in New Quizzes exported as ordinary Classic QTI 1.2 here.**
Same `question_type` metadata fields, same structure, and the course export
carries it with `submission_types=online_quiz` and no LTI, no `external_tool`
and no `quizzes.next` reference anywhere in the package. Do not assume the
authoring engine determines the export format; check the artifact.

**The empty export is still unexplained.** The same generator produced the empty
manifest and the full one, so it is not a New Quizzes / Classic distinction.
Two things differed between the runs — the quiz was unpublished for the first
and published for the second, and the route was different — so neither has been
isolated. Report the symptom, not a cause.

**An empty quiz is not necessarily a bug.** Instructure's own summer template
ships eleven quizzes with no questions, as shells for the instructor to fill,
with the real questions in separate question banks. `validate_package` reports
empty quizzes as a note and does not fail them.

## Pattern: published or unpublished

Decide this **before** building, because it is asymmetric: content that imports
published is visible to students the moment the import finishes, and putting
that back is one click per page.

```python
b = ImsccBuilder("ART 232", build, published=False)   # whole package staged
b.add_page_resource("Week 1", html, published=True)   # except this one
mod = b.new_module("Unit 3", published=False)
```

Everything inherits the builder's default and may override it: pages,
assignments, modules and module items.

**Canvas does not spell the state consistently, and guessing gets it wrong:**

| Object | Published | Unpublished |
|---|---|---|
| Page (`<meta name="workflow_state">`) | `active` | `unpublished` |
| Module (`module_meta.xml`) | `active` | `unpublished` |
| Module item (`module_meta.xml`) | `active` | `unpublished` |
| Assignment (`assignment_settings.xml`) | **`published`** | `unpublished` |

A module item defaults to the state of the **page or assignment it points at**,
not to its module, so the two cannot silently disagree. That ordering comes from
the exports: across three real courses, `unpublished` items on `active` pages
occur, and `active` items on `unpublished` pages never do. An item cannot be
more published than its content, and `validate_package` reports it as a failure
if it is.

An unpublished **module** hides everything inside it whatever the items say,
which makes it the cheapest way to stage a unit and reveal it later.

## Pattern: "Use this rubric for grading"

This flag lives on the **association between a rubric and an assignment**, not
on the rubric. That has one consequence worth knowing before you plan a build:

```python
rid = b.add_rubric("Print 1", criteria, points_possible=100.0)
b.add_assignment_resource("Print 1", html, group,
                          rubric_id=rid)               # ticked by default
b.add_assignment_resource("Print 2", html, group,
                          rubric_id=rid, rubric_use_for_grading=False)
```

**A rubrics-only package cannot carry it.** There is no assignment in the
package, so there is no association, so every rubric has to be attached by hand
in Canvas and the box ticked by hand. That is inherent to the shape, not a
defect, and `validate_package` says so rather than leaving you to wonder.

When the assignment and the rubric ship together, the box arrives already
ticked. `validate_package` reports how many assignments carry a rubric and how
many of those grade with it, so the question is answerable without unzipping
anything.

## Pattern: external links in a module

A link to something outside Canvas is a module item of type `ExternalUrl`, and
it takes **two** representations that have to agree, because two different
readers consume two different halves of it:

```python
b.add_item(mod, "ExternalUrl", "Collection of Aquatint Prints",
           url="https://collections.example.org/search/aquatint")
```

`add_item` writes both for you. What it writes, matching a real Canvas export
element for element:

| Where | What | Read by |
|---|---|---|
| `course_settings/module_meta.xml` | `<url>` on the item | **Canvas**, on import |
| `<gid>.xml` at the zip root | an `imswl_xmlv1p1` weblink | the cartridge viewer, other LMSes |
| `imsmanifest.xml` | `<resource type="imswl_xmlv1p1">` with no `href` attribute, its file declared only as a `<file>` child | both |

Two spellings in `module_meta.xml` look like mistakes and are not. The item's
`<identifierref>` points at **its own identifier**, not at the weblink
resource, while the `<organizations>` item points at the weblink resource.
Canvas exports it exactly that way. And `<new_tab>` is `true` here, where every
other item type exports `false`.

**The failure mode is total silence.** An `ExternalUrl` item with no `<url>` is
still well-formed XML, still passes a manifest parse, and still shows a title
in `module_meta.xml`. Canvas has nothing to link to, so it drops the item on
import and says nothing; the cartridge viewer shows a dead entry. Nothing
anywhere tells you a link is gone. This shipped in a real package on
2026-09-10, found only because the instructor noticed a link missing after a
"zero problems" import.

Both halves are now checked. `add_item` refuses an `ExternalUrl` with no url,
and `validate_package` reports a url-less external link as a hard failure and a
weblink-less one as a note.

While fixing it: `add_item` used to pass `content_type` straight through
unchecked, so a typo or an unsupported type produced a perfectly valid item
that imported as nothing. It now raises on anything outside `WikiPage`,
`Attachment`, `Assignment`, `ExternalUrl` and `ContextModuleSubHeader`.

## Pattern: instructor-only notes

Any page meant to be adapted by another instructor benefits from a visible
"delete this before students see it" callout. Plain prose gets missed.

Two things are easy to get wrong:

- **The label must be real text in the HTML, not a CSS `::before`
  pseudo-element.** Generated content is not real DOM text and vanishes the
  instant anyone copies the text out of the page.
- **The highlight must be an actual `<mark>` tag.** Canvas **strips inline
  `<style>` blocks out of every page on import** — confirmed by round-trip:
  103 pages lost their CSS, all 10 `<mark>` tags survived. Any page-level
  stylesheet you write is build-time decoration that will not exist in the
  live course.

## Pattern: a targeted package for a course you cannot rebuild

A full reimport needs an empty shell, which may need admin help to create.
When you only need to add or fix part of a live course, ship only that part:

- Declare **no modules and no pages** — an empty `<organizations>` tree and an
  empty `modules` element in `module_meta.xml`. Canvas imports the resources
  and touches nothing that already exists, so there is no duplication risk.
- Include only the files the imported content actually references. Include them
  even when they already exist in the destination course: the link would resolve
  either way, but a package that cannot be validated on its own is a package
  nobody can check.
- If the assignments belong in assignment groups that already exist in the
  destination course, construct the builder with
  `external_assignment_groups=True` and ship no `assignment_groups.xml`. Expect
  to move the assignments into the right group by hand: Canvas ignores the
  identifier and creates an "Imported Assignments" group. Shipping the groups
  instead is worse, because they duplicate and that reweights the gradebook.
  Without the flag, `validate()` fails an assignment that has no declared group,
  and it should: in a normal build that is a bug.
- Build it from the **same source** as the full package, so the two cannot
  drift. A proxy object that wraps the builder and swallows `new_module` /
  `add_item` / `add_page_resource` lets the same content function run
  unmodified for both.
- Canvas never deletes on import. Anything the targeted package supersedes has
  to be deleted by hand afterwards.

**A targeted package can ADD, but it cannot UPDATE.** This is the hard limit of
the pattern. Know it before you build one.

Reusing the identifier the live course already has for something does **not**
make Canvas recognise it and overwrite it. It imports a second copy. Both tested
directly against a live course on 2026-09-05:

| Shipped with the live identifier | What Canvas did |
|---|---|
| A wiki page | Imported a **duplicate**. The module item stayed on the original. |
| An assignment | Imported a **duplicate**, and put it in a **new group called "Imported Assignments"**, ignoring the `assignment_group_identifierref` naming a group that already existed. |

The assignment case is worth dwelling on, because it means a targeted package
cannot put an assignment into an existing grading category *at all*. Shipping
`assignment_groups.xml` to fix that is worse, not better: groups duplicate like
everything else, and a duplicated weighted group silently reweights a live
gradebook. So ship no groups, use `external_assignment_groups=True` so
`validate()` stops objecting, and move the assignment by hand afterwards.

When part of a live course needs *changing* rather than *adding*:

- **One or two items: edit them in Canvas.** Faster than any package, every
  time. This is the answer far more often than it feels like it should be.
- **Many items:** ship them as new, delete the old ones by hand, and expect to
  fix module items and assignment groups yourself. Budget for that rather than
  being surprised by it.
- **A whole course:** get an empty shell and reimport properly.
- **If you have API access, use it.** Updating existing objects in place is
  precisely what the REST API does and what this format cannot.

Rubrics and files were not tested separately. Assume they duplicate too; that is
now the pattern twice over.

---

## Gotchas

Every one of these is a real bug that shipped, not a hypothetical.

- **Do not percent-encode `href` values in the manifest.** The filenames
  inside the zip keep their literal characters, so an encoded href points at a
  file that does not exist. Canvas's own exports use literal, XML-escaped-only
  paths. Use `xml.sax.saxutils.escape()`, not `urllib.parse.quote()`.

- **`escape()` does not escape quote characters by default.** A filename
  containing a literal `"` breaks a double-quoted XML attribute unless you pass
  an entity map: `escape(s, {'"': "&quot;"})`.

- **Attribute order in the manifest is not fixed.** Canvas writes page
  resources as `<resource identifier=... type=... href=...>` and file
  resources as `<resource type=... identifier=... href=...>`. Any regex
  assuming one order silently under-reports. Match the block, then look inside
  it.

- **Manifest hrefs are XML-escaped; zip entry names are not.**
  `web_resources/Presentations &amp; PDFs/x.pdf` is
  `web_resources/Presentations & PDFs/x.pdf` in the archive. Unescape before
  checking existence, or every file with an ampersand looks missing.

- **`$IMS-CC-FILEBASE$` links are encoded twice**, percent-encoded and then
  XML-escaped, and **Canvas's percent-encoding is not `urllib.parse.quote`'s**:
  Canvas leaves commas literal, so `Dec 15, 2021` becomes `Dec%2015,%202021`.

- **`ExternalUrl` module items break referential integrity on purpose.** Their
  `<identifierref>` in `module_meta.xml` points at the `<item>` identifier in
  `<organizations>`, not at a `<resource>`, because the URL lives in the item.
  A validator requiring every `identifierref` to resolve to a resource reports
  false failures on them. They are *also* backed by an `imswl_xmlv1p1` resource
  with its own `.xml` file, so removing the module item alone orphans it.

- **Announcements come in pairs.** Each is an `imsdt_xmlv1p1` topic resource
  plus an `associatedcontent` meta resource it names in a `<dependency>`.
  Remove both resources and both files. A discussion topic
  (`<type>topic</type>`) is not an announcement
  (`<type>announcement</type>`).

- **Canvas normalises accented characters in page slugs.** It derives the URL
  from the page *title*, so `Albín Brunovský` becomes `albin-brunovsky`. Fold
  accents in your slugify or every export-and-diff picks up noise.

- **Due dates are UTC, all-day dates are local.** An all-day assignment due at
  11:59pm local is written at hour `offset - 1` on the *following* UTC day.
  Getting this off by one is easy and invisible. Leave one assignment untouched
  and compare against what Canvas itself wrote.

- **Canvas copies a file's original name into `<img alt>`.** Renaming the file
  does not remove the name from pages that embed it, so student work filed
  under students' names keeps announcing those names to a screen reader.
  Rewrite the alt text too, and replace it with something descriptive rather
  than emptying it.

- **"Missing links found in imported content" usually predates you.** Canvas
  reports this when a page body holds a `$CANVAS_OBJECT_REFERENCE$/modules/<id>`
  or `$CANVAS_COURSE_REFERENCE$/file_ref/<id>` that resolves to nothing in the
  package. These are Canvas's placeholders for a module or file *in this
  course*, and they are rewritten on export and copied blindly from course to
  course, so a dead one can ride along for years and several copies. One course
  carried a "Start Here" button whose target module belonged to a course two
  generations back. Check the source export before assuming a rollover
  introduced it, then delete the element rather than trying to repoint it.

- **Empty directory entries survive.** A zip records folders as their own
  entries; move every file out and Canvas still shows the empty folder.

- **Course storage quota is generous.** A real export's `course_settings.xml`
  shows a 2 GB default. Packages over 1 GB import fine. Do not over-optimise
  for size, but do check for byte-identical duplicates — one course carried the
  same 113 MB PDF at two paths, one of them referenced by nothing.

- **Python-Markdown ignores markdown inside raw HTML blocks** unless the block
  carries `markdown="1"` AND the `md_in_html` extension is enabled.

- **`<mark>` does not survive pandoc's markdown-to-docx conversion.** Raw HTML
  tags with no native AST mapping get dropped; the text survives, the styling
  does not.

- **Rate limits are real** if you are sourcing images from an external API.
  Use proper backoff, honour `Retry-After`, and run it in the background.
  Filename heuristics for picking the *right* image are unreliable — verify
  visually. One top-scoring "portrait of the artist" file was not the artist's
  work at all.

- **Never construct an outside URL from a pattern.** A guessed
  museum-collection URL 301'd to a completely different artist's page, and a
  status-code check called it a pass. Fetch it and confirm the page is about
  what you think it is.

---

## Validation checklist

Before handing off any `.imscc`:

1. **Every `.xml` parses.** `python3 -m canvas_imscc.validate_package` does
   this first and stops if it fails, because nothing else means anything if
   the manifest is malformed.
2. `course_settings/canvas_export.txt` is declared as a resource.
3. Every declared file exists as a real **zip entry**, not just on disk.
4. Every organizations `identifierref` resolves to a declared resource.
5. Every `module_meta` reference resolves (allowing the `ExternalUrl`
   exception).
6. Assignment group weights sum to 100.
7. No dangling `$IMS-CC-FILEBASE$`, `$CANVAS_OBJECT_REFERENCE$` or
   `$CANVAS_COURSE_REFERENCE$` links.
8. No personal data in file contents **or in zip entry names**.
9. No empty directory entries.
9b. Every rubric's criteria sum to its `points_possible`, and every rating
    scale tops out at its criterion's points.
10. Eyes on it in the cartridge viewer, **and** on Canvas's own Select
    Content screen at import time. They can disagree.
11. Once, after the first import: round-trip and diff.

**And the meta-rule.** Two of the worst bugs here were not caught by any check,
because the checks quietly stopped applying: a validator that only used regexes
never noticed the manifest was invalid XML, and a link verifier whose pattern
no longer matched a changed data shape skipped four links while printing a
clean pass. Parse the artifact you are editing, and when you change the shape
of your data, confirm your checker still sees it. A check that fails loudly is
doing its job; one that passes quietly may not be looking.
