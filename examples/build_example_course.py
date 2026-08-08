#!/usr/bin/env python3
"""A complete, runnable Canvas course package. Copy this and edit it.

    python3 examples/build_example_course.py
    python3 -m canvas_imscc.validate_package "/tmp/EXAMPLE 101.imscc"

Then upload the result to https://common-cartridge-viewer.netlify.app/ and
look at it before anyone imports it.

The point of this file is the SHAPE, not the content: content lives in
course_content.py, this is only assembly. Keep that split in your own build.
"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # so canvas_imscc is importable
sys.path.insert(0, str(HERE))          # so course_content is importable

from canvas_imscc.builder import ImsccBuilder
from canvas_imscc.rollforward import due_fields, set_due
import course_content as C

BUILD_DIR = os.environ.get("BUILD_DIR", "/tmp/example_course_build")
OUT = os.environ.get("OUT", "/tmp/%s.imscc" % C.COURSE_CODE)


def main():
    b = ImsccBuilder(
        course_title=C.COURSE_TITLE,
        build_dir=BUILD_DIR,
        # Set these to your own institution. They land in context.xml.
        canvas_domain="canvas.instructure.com",
        root_account_name="Your Institution",
    )

    # 1. Gradebook categories, before any assignment can reference one.
    groups = {title: b.add_assignment_group(title, weight)
              for title, weight in C.ASSIGNMENT_GROUPS}

    # 2. A real rubric, so the instructor grades with it rather than reading a
    #    heading in the description.
    project_rubric = b.add_rubric("Project Rubric", C.PROJECT_RUBRIC)

    # 3. Pages.
    page_ids = {}
    for title, body in C.PAGES:
        page_ids[title] = b.add_page_resource(title, C.DRAFT_NOTE + body)

    # 4. Assignments. Note the due date handling: due_at is UTC, all_day_date
    #    is local, and an all-day deadline lands on the FOLLOWING UTC day.
    assignment_ids = {}
    for title, group, points, submission, due, body in C.ASSIGNMENTS:
        rid = b.add_assignment_resource(
            title, C.DRAFT_NOTE + body, groups[group],
            points_possible=points,
            submission_types=submission,
            rubric_id=project_rubric if title == "Project 1" else None,
        )
        assignment_ids[title] = rid
        if due:
            path = pathlib.Path(BUILD_DIR) / rid / "assignment_settings.xml"
            path.write_text(set_due(path.read_text(),
                                    *due_fields(due, utc_offset=C.utc_offset(due))))

    # 5. A file in Course Files, if you have one. Folder structure under
    #    web_resources/ is preserved exactly as you name it here.
    #
    # rid = b.add_file_resource("Handouts/syllabus.pdf", src_path="/path/to/syllabus.pdf")
    # b.add_item(mod, "Attachment", "Syllabus", rid)

    # 6. Modules. Canvas modules do NOT nest; indent is how you fake nesting.
    lookup = {**page_ids, **assignment_ids}
    for mod_title, items in C.MODULES:
        mod = b.new_module(mod_title)
        for content_type, item_title, target, indent in items:
            b.add_item(mod, content_type, item_title,
                       lookup[target] if target else None, indent=indent)

    # 7. Write, validate, zip. Run both checks: validate() looks at the build
    #    directory, zip_package() confirms every href matches an actual entry
    #    inside the zip, which is a different and stricter question.
    b.write_manifest_and_settings()
    ok, report = b.validate()
    print(report)
    if not ok:
        return 1
    b.zip_package(OUT)
    print("\nwrote %s" % OUT)
    print("Now run:  python3 -m canvas_imscc.validate_package %r" % OUT)
    print("Then look at it: https://common-cartridge-viewer.netlify.app/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
