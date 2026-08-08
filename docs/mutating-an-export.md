# Rolling a course forward by mutating a real export

**If a previous offering of the course exists in Canvas, this is the right
approach, and it is not the obvious one.**

Ask the instructor to export the previous term (Settings > Export Course
Content > Course, wait, download the `.imscc`). Then change only what has to
change.

## Why this beats rebuilding

A genuine Canvas export already satisfies every structural requirement in
`playbook.md`, including the `course_settings` manifest declaration that
everything else hinges on. It carries through, untouched and at zero effort:

- every assignment, with its points, submission type and group
- every rubric, attached to the right assignments
- the weighted assignment groups and the grading standard
- all files, presentations, PDFs and images, in their existing folders
- discussion topics, announcements, external links, page formatting

Rebuilding those is work you do not need to do and correctness you do not need
to re-earn. A semester rollover typically touches under 5% of a package.

## The technique

Stream the source entry by entry and classify each as **drop**, **replace**,
**rename** or **copy**, then append new entries. Nothing is ever unpacked, so a
multi-gigabyte package costs time but not disk or memory.

```python
from canvas_imscc import rollforward as rf

rf.stream_rewrite(
    "spring-export.imscc", "fall-2026.imscc",
    drop={"wiki_content/old-page.html", ...},
    replace={"imsmanifest.xml": new_manifest.encode(), ...},
    rename={"web_resources/unfiled/x.pdf": "web_resources/Syllabi/x.pdf"},
    add={"wiki_content/new-page.html": html.encode()},
    transform=lambda name, data: data,
)
rf.assert_xml_parses("fall-2026.imscc")
print(rf.diff_packages("spring-export.imscc", "fall-2026.imscc"))
```

Then `python3 -m canvas_imscc.validate_package fall-2026.imscc`.

## Do this first, before anything else

**Check for student data.** A previous term's export contains real students.
One export carried two "Portfolio Review Schedule" pages listing seventeen
students by name. Those must not ride into a new course.

Drop them, and then have your validator grep the finished package for the
names as a backstop rather than trusting that the drop worked. Sweep **zip
entry names** as well as file contents: student work is often filed under
students' names, and Canvas copies the original filename into the `<img alt>`
of every page that embeds it, so the name survives in the accessibility text
long after the file is renamed.

## The bugs this pattern generates, and how to avoid each

### Parse the XML. Do not validate with regexes alone.

This cost the most time of anything in this document.

A path rewrite wrote a bare `&` into an `href` in `imsmanifest.xml`, because
the source path (`unfiled/x.pdf`) had no ampersand and the destination
(`Syllabi & Schedules/x.pdf`) did. The file was then **invalid XML**.

Every regex check still passed. Resources were declared. Hrefs resolved to real
zip entries. References matched. But no XML parser could read the manifest, so
nothing could build a resource map, and **every module item rendered as inert,
unclickable text** in both the cartridge viewer and Canvas.

`rf.assert_xml_parses()` is one call and catches the entire class instantly.

### Match many spellings, emit exactly one

The same file is spelled at least three ways in one package: literal in zip
entry names, XML-escaped in the manifest, percent-encoded-then-XML-escaped
behind `$IMS-CC-FILEBASE$` in page HTML. And Canvas's percent-encoding is not
`urllib.parse.quote`'s — it leaves commas literal.

The bug above came from pairing old spellings against new spellings and
replacing plain-with-plain, escaped-with-escaped. That is wrong the moment the
two paths need different escaping.

Use `rf.path_spellings()` to match any spelling, and `rf.xml_href()` /
`rf.html_href()` to emit the one the destination format requires.

A related trap: if you build parallel old/new variant lists to `zip()`
together, **do not deduplicate them**. A path with no spaces quotes to itself,
one list gets shorter, and `zip` silently drops the tail.

### Fail loudly when a path is not found

Filenames contain characters that look ordinary and are not. A macOS
screenshot was stored as `8.55.41 PM.png` with a NARROW NO-BREAK SPACE
(U+202F). A remap keyed on a normal space matched nothing and failed in
silence.

`rf.assert_paths_exist()` turns that into an immediate build failure.

### Removing something usually means removing three things

- **An ExternalUrl link** is a module item, *plus* an `imswl_xmlv1p1` resource,
  *plus* that resource's `.xml` file. Drop only the item and you orphan the
  rest, and no structural check notices. Use `rf.weblink_resources()`.
- **An announcement** is a topic resource *plus* the `associatedcontent` meta
  resource it names in a `<dependency>`, and both files. Use
  `rf.announcement_resources()`.
- **A module subheader** exists in `module_meta.xml` *and* in the manifest
  organizations tree, as an item with a title and no `identifierref`.
- **A file you move out of a folder** leaves the folder's own zip entry behind,
  so Canvas still shows an empty folder. Use `rf.emptied_dirs()`.

### Match assignments by resource id, never by title

Titles are not unique. One course had a "Planar Analysis" **assignment** and a
"Planar Analysis" **presentation PDF** as separate module items with identical
titles. A title-keyed removal takes both.

Resolve the title to a resource id once, then work with the id.

### Due dates are off by one if you are not careful

`due_at` is UTC; `all_day_date` is the local date. An all-day assignment due at
11:59pm local is written at hour `offset - 1` on the **following** UTC day.
Use `rf.due_fields()`, and pass the offset explicitly — only you know the
course's timezone and where its daylight-saving boundary falls within the term.

The cheap confirmation: leave one assignment's date untouched and compare your
output against what Canvas itself wrote.

### Verify by diffing against the source

Do not trust your own checks alone. `rf.diff_packages()` lists what was added,
removed and modified. This is the round-trip rule applied *before* import
instead of after, and it is what catches an edit that reached more entries than
you intended.

Work in passes, and diff after each one. Six small verified passes beat one
large unverified one.

## Things worth doing while you are in there

A rollover is the natural moment for housekeeping the instructor will not think
to ask for:

- **Check for byte-identical duplicates.** One course carried the same 113 MB
  PDF at two paths, one referenced by nothing. Dropping it saved 117 MB.
- **Look for orphaned resources** — declared in the manifest but referenced by
  no module item. They are invisible in Modules but real in the course. One
  course had a whole Classwork page students could not reach from Modules,
  which had been true for at least a term before anyone noticed.
- **Update dates written inside assignment bodies.** A brief that says
  "CRITIQUE: APRIL 9TH" or a file-naming convention stamped with the term
  (`ART101_S26_Lastname`) is stale text no date field will fix. Rewrite these
  as exact string replacements that **fail the build if they do not match**, so
  the rest of the instructor's prose cannot drift.
- **Ask about anything unpublished or zero-point.** Old placeholder assignments
  accumulate. The instructor usually wants them gone and has forgotten they
  exist.

## Ordering

Some operations invalidate offsets or interact. A safe order:

1. Resolve everything you are removing to resource ids, and fail if any is
   missing.
2. Edit `module_meta.xml`: drop items, merge or rename modules, then place
   additions.
3. Edit `imsmanifest.xml`: drop resources and organizations items, then the
   same merges and renames, then declare new resources, then mirror additions.
4. Stream the zip with the drops, renames, replacements and additions.
5. Parse every XML, validate, diff against the source.

Recompute positions and spans after any structural edit rather than caching
them. Removing one block moves every offset after it.
