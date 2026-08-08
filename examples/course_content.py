#!/usr/bin/env python3
"""Everything this example course SAYS, with none of the logic for saying it.

Keeping content in its own module is the single most useful structural habit
in this kit. You will edit this file constantly and the build script rarely,
and because one source drives everything, the package and any spreadsheet or
handout you also generate from it cannot drift apart.

Replace all of this with your own course. Nothing here is special.
"""

COURSE_TITLE = "EXAMPLE 101 - Introduction to Something"
COURSE_CODE = "EXAMPLE 101"

# Gradebook categories. Weights must sum to 100 if you use weighting at all.
ASSIGNMENT_GROUPS = [
    ("Exercises", 40.0),
    ("Projects", 40.0),
    ("Participation", 20.0),
]

# The course timezone, as hours WEST of UTC. Two values because most terms
# cross a daylight-saving boundary, and getting this wrong shifts every
# all-day due date by an hour. US Eastern: 4 in daylight time, 5 in standard.
UTC_OFFSET_BEFORE_DST_ENDS = 4
UTC_OFFSET_AFTER_DST_ENDS = 5
DST_ENDS = "2026-11-01"


def utc_offset(datestr):
    return (UTC_OFFSET_BEFORE_DST_ENDS if datestr < DST_ENDS
            else UTC_OFFSET_AFTER_DST_ENDS)


# A visible note for anything the instructor has not read yet. It must be a
# real <mark> tag: Canvas strips inline <style> blocks out of every page on
# import, so a CSS class alone would render as plain text in the live course.
DRAFT_NOTE = (
    '<p><mark><strong>DRAFT.</strong> Written ahead of the term. Check each '
    'entry and delete this note before students see the page.</mark></p>'
)


# (title, body HTML) for each Canvas Page.
PAGES = [
    ("Course Schedule", """<h2>Course Schedule</h2>
<p>Meetings, topics and due dates. This schedule is a plan, not a contract.
Dates for in-class work will move; the due dates in Canvas are the ones that
count.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
<thead><tr><th>Week</th><th>Date</th><th>In class</th><th>Due</th></tr></thead>
<tbody>
<tr><td>1</td><td>Tue, Sep 1</td><td>Introduction and syllabus</td><td></td></tr>
<tr><td>2</td><td>Tue, Sep 8</td><td>First topic</td><td>Exercise 1</td></tr>
<tr><td>3</td><td>Tue, Sep 15</td><td>Second topic</td><td></td></tr>
</tbody>
</table>"""),

    ("Studio Policies", """<h2>Studio Policies</h2>
<ul>
<li>Clean your space before you leave.</li>
<li>Put tools back where you found them.</li>
</ul>"""),
]


# (title, group, points, submission type, due date, body HTML).
#
# submission_types: "online_upload" for anything turned in digitally,
# "on_paper" for work handed in physically or reviewed in person, "none" for a
# gradebook line with no submission at all. Choosing "on_paper" matters: an
# online_upload assignment puts an upload box in front of students for work
# they are meant to carry into the room.
ASSIGNMENTS = [
    ("Exercise 1: A Short Exercise", "Exercises", 100.0, "on_paper", "2026-09-08",
     """<h3><strong>SUMMARY</strong></h3>
<p>What the student is practising, and why, in a sentence or two.</p>
<h3><strong>CONSTRAINTS/CONDITIONS</strong></h3>
<ul>
<li>A specific, checkable constraint.</li>
<li>Another one.</li>
<li>Evidence of change should be visible in the finished work.</li>
</ul>"""),

    ("Project 1", "Projects", 100.0, "online_upload", "2026-10-20",
     """<h3><strong>SUMMARY</strong></h3>
<p>The larger piece of work, its purpose and its scope.</p>
<h3><strong>CONSTRAINTS/CONDITIONS</strong></h3>
<ul>
<li>Size, medium, or format requirements.</li>
</ul>
<h3><strong>DIGITAL SUBMISSION</strong></h3>
<ul>
<li>Combine everything into one PDF.</li>
<li>File naming: <strong>EXAMPLE101_FA26_Firstname_Lastname_Project1</strong></li>
</ul>"""),

    # No due date, no submission: a gradebook line the instructor fills in.
    ("Participation", "Participation", 100.0, "none", None,
     """<h3><strong>SUMMARY</strong></h3>
<p>Attendance with materials, engagement in critique, attention during
demonstrations, active work time, cleaning up afterwards.</p>"""),
]


# A rubric attached to a real assignment, so the instructor grades with it
# rather than reading a "RUBRIC" heading in the description. Keep both: the
# text is what a student reads, the rubric is what the instructor grades with.
#
# (criterion, points, long description, [(rating label, points), ...])
# Ratings run highest first, and the top rating must equal the criterion's
# point value or validate() will say so.
PROJECT_RUBRIC = [
    ("Process", 40.0, "Evidence of sustained work, revision and improvement.",
     [("Sustained and visible", 40.0), ("Present", 30.0),
      ("Thin", 20.0), ("Absent", 0.0)]),
    ("Execution", 40.0, "Technical control appropriate to this stage of the course.",
     [("Assured", 40.0), ("Competent", 30.0),
      ("Uneven", 20.0), ("Not yet", 0.0)]),
    ("Engagement", 20.0, "Participation in critique and studio practice.",
     [("Active throughout", 20.0), ("Usually present", 15.0),
      ("Intermittent", 10.0), ("Absent", 0.0)]),
]


# (module title, [(content_type, title, page-or-assignment title or None, indent)])
# content_type is WikiPage, Assignment, Attachment or ContextModuleSubHeader.
# A ContextModuleSubHeader is a plain text divider and references nothing.
MODULES = [
    ("Course Information", [
        ("WikiPage", "Course Schedule", "Course Schedule", 0),
        ("WikiPage", "Studio Policies", "Studio Policies", 0),
    ]),
    ("Unit 1", [
        ("ContextModuleSubHeader", "Assignments", None, 0),
        ("Assignment", "Exercise 1: A Short Exercise", "Exercise 1: A Short Exercise", 1),
        ("Assignment", "Project 1", "Project 1", 1),
    ]),
    ("Gradebook", [
        ("Assignment", "Participation", "Participation", 0),
    ]),
]
