---
name: build-canvas-course
description: Build a Canvas .imscc course package, or roll an existing course forward to a new term, guided end to end
argument-hint: [course name or path to a previous term's .imscc export]
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, WebFetch]
---

# Build a Canvas course package

Guide the instructor from source material to a validated `.imscc` file they can
import into Canvas.

Load the `canvas-course-packaging` skill for the full rules, the format details
and the symptom index. This file is the workflow; that one is the knowledge.

## Argument

`$ARGUMENTS` may be a course name, a path to a previous term's `.imscc` export,
a path to a folder of source material, or empty. If it is empty, ask what the
course is and whether a previous export exists.

## 0. Confirm this is the right tool

Ask whether the instructor has a working Canvas API token. If they do, the REST
API is much simpler and they should use it. This kit exists for institutions
that have disabled personal access tokens.

## 1. Choose the path

If a previous offering exists, get the export and **mutate it**. Ask them to go
to Settings > Export Course Content > Course, wait for the email, and download
the `.imscc`. This is almost always the right path and instructors rarely expect
it. Otherwise build from scratch.

## 2. Interview

Ask the questions listed in the `canvas-course-packaging` skill: title and code,
weighted assignment groups and their percentages, which items must be real
Assignments rather than Pages, timezone and any daylight-saving boundary, and
where the source material lives. Ask them one at a time if they prefer. State an
assumption and keep moving rather than blocking on anything you can default.

Also confirm **where the build script should live**. It belongs in the
instructor's own project directory, under version control if they have it, not
inside the plugin.

## 3. Verify the toolchain before building anything

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 "${CLAUDE_PLUGIN_ROOT}/tests/smoke_test.py"
```

This builds, validates, mutates and deliberately breaks a package to prove the
checks actually fire. Requires Python 3.8+ and no dependencies.

## 4. Build

Write a build script in the instructor's directory that imports the library and
keeps **content separate from build logic**, because content changes far more
often and the separation is what stops the package and any spreadsheet or
handout from drifting apart.

Then, in order, and run all of them:

```bash
python3 build_my_course.py     # calls b.validate() then b.zip_package()
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m canvas_imscc.validate_package "Course.imscc"
```

`b.validate()` checks the model; `b.zip_package()` catches a mismatch between
the manifest and the actual zip entries rather than files that merely exist on
disk. `validate_package` re-checks the finished artifact from the outside.

If the package derives from a real course, re-run the validator with `--names`
and every student name that must not appear. Canvas copies original filenames
into `<img alt>`, so renaming a file does not remove a name from the package.

## 5. Hand off with both previews

Do not tell the instructor the package is ready until you have told them both of
these, because the two can disagree and the disagreement runs in the dangerous
direction:

1. Upload the `.imscc` to <https://common-cartridge-viewer.netlify.app/> and
   look at the module tree. It runs locally in the browser; nothing is uploaded
   anywhere.
2. Import into an **empty course shell**, Settings > Import Course Content,
   Content Type "Canvas Course Export Package", and choose **"Select specific
   content"** rather than "All content". That screen is Canvas's own importer
   reporting what it found. If assignments appear under Assignments, the package
   is right. If they appear only as Pages, stop, and fix the `course_settings`
   resource declaration before importing.

Warn them explicitly that Canvas never deletes on import, so a bad import into a
non-empty course has to be undone by hand, one checkbox at a time.

## 6. Close the loop after the first import

Ask the instructor to export the course back out of Canvas and diff it against
what you built. Nothing in steps 3 through 5 tells you what Canvas actually did.
Compare the `<content_type>` counts in `course_settings/module_meta.xml` first.

Report honestly: if a check was skipped or a step could not be run, say so
plainly rather than implying the package is verified.

## 7. Report anything the docs did not predict

If Canvas did something these docs do not describe, tell the instructor, and
offer to open an issue with the sanitized template. See the "If Canvas does
something these docs do not describe" section of the `canvas-course-packaging`
skill. Do not just quietly route around it.
