#!/usr/bin/env python3
"""
Reusable engine for hand-building a Canvas Course Export Package (.imscc).

Why this exists: many institutions disable personal API access token
creation, which closes off the obvious route of scripting a course through
Canvas's REST API. A Course Export Package is the workaround. Any teacher
can import one through Settings > Import Course Content > "Canvas Course
Export Package" with no admin permission, and it is the exact zip format
Canvas itself produces via Settings > Export Course Content. So you
hand-build the file Canvas would have produced and let Canvas's own
importer do the rest.

See docs/playbook.md for the schema notes and the list of real bugs found
and fixed while building courses with this.

This module is the engine: registries, page/file/assignment resource
helpers, and the manifest / module_meta / course_settings XML writers. It
has no content of its own. A calling script defines the modules, pages and
files for one specific course, then calls write_manifest_and_settings(),
validate() and zip_package().

Minimal usage:

    from canvas_imscc.builder import ImsccBuilder

    b = ImsccBuilder(course_title="My Course", build_dir="/tmp/my_course_build")

    resources_mod = b.new_module("Resources")
    rid = b.add_file_resource("Resources/glossary.pdf", src_path="/path/to/glossary.pdf")
    b.add_item(resources_mod, "Attachment", "Glossary", rid)

    week_mod = b.new_module("Week 1")
    b.add_item(week_mod, "ContextModuleSubHeader", "Readings")
    rid = b.add_page_resource("Week 1 Overview", "<h2>Week 1</h2><p>...</p>")
    b.add_item(week_mod, "WikiPage", "Week 1 Overview", rid, indent=1)

    b.write_manifest_and_settings()
    ok, report = b.validate()
    print(report)
    if ok:
        b.zip_package("/tmp/My Course.imscc")

Set canvas_domain and root_account_name to your own institution's. They go
into course_settings/context.xml. Canvas does not appear to validate them
on import, but keeping them accurate costs nothing.
"""
import re
import html
import secrets
import unicodedata
import pathlib
import shutil
import zipfile
import urllib.parse
from xml.sax.saxutils import escape as xesc


def gid():
    """Canvas-style opaque identifier: a lowercase 'g' plus 32 hex chars."""
    return "g" + secrets.token_hex(16)


def slugify(name):
    # Fold accents to their base letters first, the way Canvas does when it
    # builds a page URL from a title. Without this, "Albín Brunovský" becomes
    # "alb-n-brunovsk" here but "albin-brunovsky" once Canvas has it, which
    # doesn't break anything (Canvas derives the URL from the title, not our
    # filename) but makes every export-and-diff reconciliation noisier than
    # it needs to be. Six artists hit this. Confirmed against a real export,
    # 2026-08-06.
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


class ImsccBuilder:
    def __init__(self, course_title, build_dir, canvas_domain="canvas.instructure.com",
                 root_account_name="Your Institution", extra_head_html="",
                 external_assignment_groups=False, published=True):
        # external_assignment_groups: this package's assignments name assignment
        # groups that already exist in the DESTINATION course, by identifier,
        # and the package deliberately ships no assignment_groups.xml. Only
        # meaningful for a targeted package added to a live course.
        #
        # Canvas does NOT honour that identifier. Tested against a live course
        # on 2026-09-05: the assignment landed in a new group called "Imported
        # Assignments" and had to be moved by hand. Setting this flag does not
        # avoid that; it only stops validate() failing a package that is
        # correctly built for a job Canvas cannot do cleanly. Shipping the
        # groups instead is worse, because they duplicate too and that silently
        # reweights a live gradebook. See docs/playbook.md.
        #
        # Leave this False for a normal build, where an assignment with no
        # declared group IS a bug.
        self.external_assignment_groups = external_assignment_groups
        # Whether content ships published (visible to students) or unpublished.
        # This is a COURSE-WIDE default that every page, assignment, module and
        # module item inherits and may override. Decide it before building:
        # importing published content into a live course shows it to students
        # the moment the import finishes, and unpublishing 60 pages afterwards
        # is one click at a time.
        self.published = published
        self.course_title = course_title
        self.canvas_domain = canvas_domain
        self.root_account_name = root_account_name
        # Injected verbatim into every Page's <head>, e.g. a shared <style>
        # block. Keep it small: it's duplicated into every generated page.
        self.extra_head_html = extra_head_html

        self.build = pathlib.Path(build_dir)
        self.wiki = self.build / "wiki_content"
        self.web = self.build / "web_resources"
        self.cs = self.build / "course_settings"
        for d in (self.wiki, self.web, self.cs):
            d.mkdir(parents=True, exist_ok=True)

        self.resources = []  # [{id, type:'page'|'file', href, title, published}]
        # resource id -> published, so a module item can default to the state of
        # the thing it points at rather than to the course default.
        self.resource_published = {}
        self.modules = []    # [{id, title, items:[{id, content_type, title, resource_id, indent}]}]

    # -- Page / file resources ------------------------------------------------

    # Canvas does not spell these consistently, and this is easy to get wrong:
    # pages, modules and module items use active/unpublished, while assignments
    # use published/unpublished. Both spellings are taken from real exports.
    @staticmethod
    def _state(published):
        return "active" if published else "unpublished"

    def _page_html(self, title, body_html, ident, published=True):
        return f"""<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>{xesc(title)}</title>
<meta name="identifier" content="{ident}"/>
<meta name="editing_roles" content="teachers"/>
<meta name="workflow_state" content="{self._state(published)}"/>
{self.extra_head_html}
</head>
<body>
{body_html}
</body>
</html>
"""

    def add_page_resource(self, title, body_html, published=None):
        """Write a Canvas Page (wiki_content/*.html) and register it as a resource.
        Returns the resource id to pass to add_item().
        published: None inherits the course-wide default set on the builder."""
        rid = gid()
        slug = slugify(title)[:60] or gid()
        fname = f"{slug}.html"
        n = 1
        target = self.wiki / fname
        while target.exists():
            n += 1
            fname = f"{slug}-{n}.html"
            target = self.wiki / fname
        pub = self.published if published is None else published
        target.write_text(self._page_html(title, body_html, rid, pub))
        self.resources.append({"id": rid, "type": "page", "href": f"wiki_content/{fname}",
                               "title": title, "published": pub})
        self.resource_published[rid] = pub
        # Remembered so page_link() can resolve links written before this
        # page existed. Two pages sharing a title cannot be told apart by a
        # link, so say so rather than silently pointing every link at one.
        if not hasattr(self, "page_ids"):
            self.page_ids = {}
        if title in self.page_ids:
            raise ValueError(
                "two pages are titled %r. Canvas derives a page's URL from its "
                "title, so these would collide in the live course and "
                "page_link() cannot tell them apart." % title)
        self.page_ids[title] = rid
        return rid

    def add_file_resource(self, rel_path, src_path=None):
        """Register a Course File under web_resources/<rel_path>.
        If src_path is given, copies the real file into place (creating
        parent dirs as needed) — pass None if you've already placed the
        file under web_resources/ yourself. rel_path's exact spelling
        (spaces, punctuation, quotes) must match the real filename;
        do not pre-encode it."""
        rid = gid()
        href = f"web_resources/{rel_path}"
        if src_path is not None:
            dest = self.build / href
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
        self.resources.append({"id": rid, "type": "file", "href": href,
                               "title": pathlib.Path(rel_path).name})
        return rid

    @staticmethod
    def extract_body(html_path):
        """Pull just the <body>...</body> inner HTML out of a full HTML file,
        e.g. output from a markdown-to-HTML pass, for use as a page body."""
        text = pathlib.Path(html_path).read_text()
        m = re.search(r"<body>(.*)</body>", text, re.S)
        return m.group(1).strip()

    # -- Assignments (gradebook-integrated, distinct from Pages) ---------------
    #
    # Confirmed by reading a real Canvas export, not guessed. An
    # Assignment is a *different* resource type than a Page: it needs its
    # own folder (named after its resource id, at the package root — not
    # under wiki_content/ or web_resources/) containing the description
    # HTML plus a Canvas-specific assignment_settings.xml. It also needs an
    # Assignment Group to belong to (Studies, Midterm, Extended Drawings,
    # Participation, Final, ... — these map directly onto the syllabus's
    # grading category weights) declared once in course_settings/assignment_groups.xml.

    def add_syllabus(self, body_html):
        """Fill Canvas's dedicated Syllabus page (Course > Syllabus).

        Not a Page and not a module item: Canvas has one built-in Syllabus per
        course, and a real export carries it as course_settings/syllabus.html
        declared in its OWN resource with intendeduse="syllabus". It is
        deliberately not listed inside the main course_settings resource;
        that is the shape a real export uses.

        Worth knowing before you go hunting: the Common Cartridge viewer does
        not render the Syllabus page, so a correct package looks like it is
        missing until you actually import it."""
        self.syllabus_html = body_html

    # -- Page-to-page links --------------------------------------------------
    #
    # The trap here cost 54 import errors in one package, every one reported
    # only as the unhelpful "Missing links found in imported content - Wiki
    # Page body", with the live links landing on "page not found".
    #
    # Canvas links a page to another page as:
    #
    #     $WIKI_REFERENCE$/pages/<RESOURCE IDENTIFIER>
    #
    # The target is the page's identifier in imsmanifest.xml. NOT a URL slug,
    # NOT the page title, and NOT $WIKI_REFERENCE$/wiki_pages/<anything> —
    # wiki_pages is the ActiveRecord model name, not a route, and it does not
    # resolve.
    #
    # A fragment needs a query string in front of it:
    #
    #     /pages/<id>                    opens the page
    #     /pages/<id>#anchor             BREAKS. Canvas absorbs the fragment
    #                                    into the identifier, finds no page,
    #                                    and offers to create one
    #     /pages/<id>?titleize=0#anchor  opens the page AND jumps to the anchor
    #
    # because canvas-lms parses the object id with UriMatch#query = rest[/\?.*/],
    # so "?" is what terminates it. All three confirmed by live import.
    #
    # The ids do not exist until the pages are added, so forward references
    # cannot be written directly. page_link() emits a placeholder and
    # write_manifest_and_settings() resolves them all once every page exists.

    def page_link(self, page_title, anchor=None):
        """An href linking to another page in this package, by its title.

        Use it while building any page, assignment or syllabus body, including
        for a page you have not added yet:

            body = 'See <a href="%s">Aquatint</a>.' % b.page_link("Aquatint")

        Resolution happens in write_manifest_and_settings(), which fails if a
        link names a page that was never added."""
        ref = "$WIKI_REFERENCE$/pages/@@%s@@" % page_title
        return "%s?titleize=0#%s" % (ref, anchor) if anchor else ref

    def _resolve_page_links(self):
        """Swap every page_link() placeholder for the real resource id.

        Every .html in the build directory, because assignment bodies and the
        syllabus link to pages too, not just other pages."""
        import re as _re
        titles = getattr(self, "page_ids", None) or {}
        missing, touched = set(), 0
        for f in self.build.rglob("*.html"):
            txt = f.read_text(encoding="utf-8")
            if "@@" not in txt:
                continue
            def sub(m):
                rid = titles.get(m.group(1))
                if rid is None:
                    missing.add(m.group(1))
                    return m.group(0)
                return rid
            new = _re.sub(r"@@(.+?)@@", sub, txt)
            if new != txt:
                f.write_text(new, encoding="utf-8")
                touched += 1
        if missing:
            raise ValueError(
                "page_link() names %d page(s) that were never added: %s"
                % (len(missing), sorted(missing)))
        return touched

    def _weighting_scheme_xml(self):
        """The one line that decides whether the weights mean anything.

        Declaring group weights in assignment_groups.xml is only half of it.
        Unless course_settings.xml also carries
        <group_weighting_scheme>percent</group_weighting_scheme>, Canvas
        imports every weight, shows them in the Assignments page, and then
        grades on straight points regardless. Nothing warns. The gradebook
        looks plausible and every final grade is wrong, which is the worst
        shape a bug can take in a course.

        So: if any group carries a non-zero weight, the course is weighted.
        A course whose groups are all zero is a straight-points gradebook and
        must NOT get this element, because that would switch weighting on with
        every category worth 0%.
        """
        groups = getattr(self, "assignment_groups", None) or []
        if any(float(g["weight"]) for g in groups):
            return "  <group_weighting_scheme>percent</group_weighting_scheme>\n"
        return ""

    def add_assignment_group(self, title, weight):
        """Register a grading category (e.g. "Studies", weight=30.0 for 30%).
        Call once per category; returns the group id to pass to add_assignment_resource()."""
        if not hasattr(self, "assignment_groups"):
            self.assignment_groups = []
        gid_ = gid()
        self.assignment_groups.append({
            "id": gid_, "title": title,
            "position": len(self.assignment_groups) + 1, "weight": weight,
        })
        return gid_

    def add_rubric(self, title, criteria, points_possible=None, use_range=True):
        """Register a real Canvas Rubric (gradeable, attaches to an assignment),
        not just a RUBRIC heading in the assignment's description text.

        criteria: list of (description, points, long_description, ratings)
        where ratings is a list of (label, points), highest first.

        Returns the rubric id, to pass to add_assignment_resource(rubric_id=...).

        Schema taken from a real Canvas export
        (course_settings/rubrics.xml). Canvas keys ratings to their criterion by
        criterion_id, and every rating needs its own <id>; the real exports use
        opaque strings there, so any stable unique value works.
        """
        if not hasattr(self, "rubrics"):
            self.rubrics = []
        rid = gid()
        total = points_possible if points_possible is not None else sum(c[1] for c in criteria)
        self.rubrics.append({
            "id": rid, "title": title, "points_possible": total,
            "use_range": use_range, "criteria": criteria,
        })
        return rid

    def add_assignment_resource(self, title, body_html, assignment_group_id,
                                 points_possible=100.0, submission_types="on_paper",
                                 rubric_id=None, rubric_use_for_grading=True,
                                 published=None):
        """Write a Canvas Assignment (folder + description HTML + assignment_settings.xml)
        and register it as a resource. Use with add_item(mod, "Assignment", ...).
        submission_types: 'on_paper' for studio work turned in physically,
        'online_upload' for anything submitted digitally (e.g. a final portfolio PDF).
        rubric_id: an id from add_rubric(), to attach a real gradeable rubric.
        rubric_use_for_grading: ticks Canvas's "Use this rubric for grading" on
        the assignment, so the rubric drives the score instead of sitting
        alongside it as a comment. Default True, and it only takes effect when
        the assignment and the rubric ship TOGETHER — a rubric imported on its
        own carries no association to tick.
        published: None inherits the course-wide default set on the builder."""
        rid = gid()
        pub = self.published if published is None else published
        slug = slugify(title)[:60] or rid
        folder = self.build / rid
        folder.mkdir(parents=True, exist_ok=True)
        html_name = f"{slug}.html"
        (folder / html_name).write_text(f"""<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>Assignment: {xesc(title)}</title>
</head>
<body>
{body_html}
</body>
</html>
""")
        (folder / "assignment_settings.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<assignment identifier="{rid}" xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <title>{xesc(title)}</title>
  <due_at/>
  <lock_at/>
  <unlock_at/>
  <module_locked>false</module_locked>
  <assignment_group_identifierref>{assignment_group_id}</assignment_group_identifierref>
  <workflow_state>{"published" if pub else "unpublished"}</workflow_state>
{self._rubric_ref_xml(rubric_id, rubric_use_for_grading)}  <assignment_overrides>
  </assignment_overrides>
  <allowed_extensions></allowed_extensions>
  <has_group_category>false</has_group_category>
  <points_possible>{points_possible}</points_possible>
  <grading_type>letter_grade</grading_type>
  <all_day>false</all_day>
  <submission_types>{submission_types}</submission_types>
  <position>1</position>
  <turnitin_enabled>false</turnitin_enabled>
  <vericite_enabled>false</vericite_enabled>
  <peer_review_count>0</peer_review_count>
  <peer_reviews>false</peer_reviews>
  <automatic_peer_reviews>false</automatic_peer_reviews>
  <anonymous_peer_reviews>false</anonymous_peer_reviews>
  <grade_group_students_individually>false</grade_group_students_individually>
  <freeze_on_copy>false</freeze_on_copy>
  <omit_from_final_grade>false</omit_from_final_grade>
  <hide_in_gradebook>false</hide_in_gradebook>
  <intra_group_peer_reviews>false</intra_group_peer_reviews>
  <only_visible_to_overrides>false</only_visible_to_overrides>
  <post_to_sis>false</post_to_sis>
  <moderated_grading>false</moderated_grading>
  <grader_count>0</grader_count>
  <grader_comments_visible_to_graders>true</grader_comments_visible_to_graders>
  <anonymous_grading>false</anonymous_grading>
  <graders_anonymous_to_graders>false</graders_anonymous_to_graders>
  <grader_names_visible_to_final_grader>true</grader_names_visible_to_final_grader>
  <anonymous_instructor_annotations>false</anonymous_instructor_annotations>
  <post_policy>
    <post_manually>true</post_manually>
  </post_policy>
</assignment>
""")
        self.resources.append({
            "id": rid, "type": "assignment", "title": title,
            "href": f"{rid}/{html_name}",
            "extra_files": [f"{rid}/assignment_settings.xml"],
            "rubric_id": rubric_id, "published": pub,
        })
        self.resource_published[rid] = pub
        return rid

    @staticmethod
    def _rubric_ref_xml(rubric_id, use_for_grading):
        """The rubric association block inside assignment_settings.xml. Sits
        between <workflow_state> and <assignment_overrides>, matching the
        element order in Canvas's own exports."""
        if not rubric_id:
            return ""
        return (
            f"  <rubric_identifierref>{rubric_id}</rubric_identifierref>\n"
            f"  <rubric_use_for_grading>{'true' if use_for_grading else 'false'}</rubric_use_for_grading>\n"
            f"  <rubric_hide_points>false</rubric_hide_points>\n"
            f"  <rubric_hide_outcome_results>false</rubric_hide_outcome_results>\n"
            f"  <rubric_hide_score_total>false</rubric_hide_score_total>\n"
        )

    # -- Modules ---------------------------------------------------------------

    def new_module(self, title, published=None):
        """published: None inherits the course-wide default. An unpublished
        module hides everything in it from students regardless of the state of
        the individual items, which makes it the cheapest way to stage a whole
        unit and reveal it later."""
        mod = {"id": gid(), "title": title, "items": [],
               "published": self.published if published is None else published}
        self.modules.append(mod)
        return mod

    ITEM_TYPES = ("WikiPage", "Attachment", "Assignment", "ExternalUrl",
                  "ContextModuleSubHeader")

    def add_item(self, mod, content_type, title, resource_id=None, indent=0,
                 url=None, new_tab=None, published=None):
        """content_type: 'WikiPage', 'Attachment', 'Assignment', 'ExternalUrl'
        or 'ContextModuleSubHeader' (a plain text divider with no resource_id,
        no click target).
        indent: 0-5, Canvas's module-item indent level — this is how you
        fake sub-modules, since Canvas Modules don't actually nest.
        url: required for, and only valid on, an 'ExternalUrl' item.
        new_tab: whether the item opens in a new tab. Defaults to True for
        ExternalUrl (matching what Canvas itself exports) and False otherwise.

        published: None follows the PAGE or ASSIGNMENT this item points at, so
        the two cannot disagree by accident, and falls back to the module's own
        state for items with no content of their own.

        content_type used to be passed straight through unchecked, so a type
        Canvas does not recognise produced a well-formed item that silently
        went nowhere. Unknown types now raise."""
        if content_type not in self.ITEM_TYPES:
            raise ValueError(
                "unknown module item content_type %r. Canvas ignores module "
                "items it does not recognise, so this would have imported as "
                "nothing at all. Known types: %s"
                % (content_type, ", ".join(self.ITEM_TYPES)))
        item = {
            "id": gid(),
            "content_type": content_type,
            "title": title,
            "resource_id": resource_id,
            "indent": indent,
            "url": url,
            "new_tab": bool(new_tab) if new_tab is not None
                       else content_type == "ExternalUrl",
            "published": (published if published is not None
                          else self.resource_published.get(resource_id,
                                                           mod["published"])),
        }
        if content_type == "ExternalUrl":
            if not url:
                raise ValueError(
                    "ExternalUrl module item %r has no url. Canvas has nothing "
                    "to link to and drops the item on import, leaving no trace "
                    "and no error." % title)
            if resource_id is not None:
                raise ValueError(
                    "ExternalUrl module item %r takes url=, not resource_id= "
                    "— the weblink resource is created for you." % title)
            # Two separate references, and they are NOT the same id. The
            # <organizations> item points at a Common Cartridge weblink
            # resource; module_meta's <identifierref> points at the item's own
            # identifier. Both spellings come straight from a real Canvas
            # export, and the url itself is what Canvas actually imports.
            item["org_ref"] = self._add_weblink_resource(title, url)
            item["resource_id"] = item["id"]
        elif url is not None:
            raise ValueError(
                "url= is only valid on an ExternalUrl module item, not %r"
                % content_type)
        mod["items"].append(item)

    def _add_weblink_resource(self, title, url):
        """Write a Common Cartridge weblink (imswl_xmlv1p1) at the zip root and
        register it. This is what makes an external link render in the
        cartridge viewer and any non-Canvas LMS; Canvas itself reads the <url>
        in module_meta.xml instead, so BOTH have to be right."""
        rid = gid()
        (self.build / f"{rid}.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<webLink xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imswl_v1p1" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imswl_v1p1 '
            'http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imswl_v1p1.xsd">\n'
            f'  <title>{xesc(title)}</title>\n'
            f'  <url href="{xesc(url, {chr(34): "&quot;"})}"/>\n'
            '</webLink>\n')
        self.resources.append({"id": rid, "type": "weblink",
                               "href": f"{rid}.xml", "title": title})
        return rid

    # -- XML writers -------------------------------------------------------

    def _resource_xml(self, r):
        # Literal path, XML-escaped only (NOT percent-encoded) — must match
        # the actual literal filenames inside the zip, which keep spaces,
        # commas, ampersands, etc. escape() alone does not escape quote
        # characters, but this value sits inside a double-quoted XML
        # attribute, so filenames containing literal " need that handled too.
        href = xesc(r["href"], {'"': "&quot;"})
        quote_map = {'"': "&quot;"}
        res_type = ("associatedcontent/imscc_xmlv1p1/learning-application-resource"
                    if r["type"] in ("assignment", "coursesettings", "syllabus") else "webcontent")
        if r["type"] == "weblink":
            # No href attribute on the resource element itself; a real Canvas
            # export declares the weblink xml only as a <file> child.
            return (f'    <resource identifier="{r["id"]}" type="imswl_xmlv1p1">\n'
                    f'      <file href="{href}"/>\n'
                    f'    </resource>\n')
        if r["type"] == "syllabus":
            files = f'      <file href="{href}"/>\n'
        elif r["type"] == "coursesettings":
            # The href file is itself one of the listed <file> entries here,
            # so don't emit it twice — match Canvas's own layout exactly.
            files = "".join(f'      <file href="{xesc(f, quote_map)}"/>\n' for f in r["extra_files"])
        else:
            files = f'      <file href="{href}"/>\n' + "".join(
                f'      <file href="{xesc(f, quote_map)}"/>\n' for f in r.get("extra_files", []))
        # intendeduse="syllabus" is how a real export marks the file that
        # becomes Canvas's dedicated Syllabus page. It is spec-defined and
        # Canvas keys on it; without it syllabus.html imports as an ordinary
        # file sitting in course_settings/ that nothing ever shows.
        use = f' intendeduse="{r["intendeduse"]}"' if r.get("intendeduse") else ""
        return (
            f'    <resource identifier="{r["id"]}" type="{res_type}" href="{href}"{use}>\n'
            f'{files}'
            f'    </resource>\n'
        )

    def _org_item_xml(self, item, depth=1):
        indent = "  " * (depth + 2)
        ref = item.get("org_ref") or item["resource_id"]
        if ref:
            return (f'{indent}<item identifier="{item["id"]}" identifierref="{ref}">\n'
                     f'{indent}  <title>{xesc(item["title"])}</title>\n{indent}</item>\n')
        return (f'{indent}<item identifier="{item["id"]}">\n'
                f'{indent}  <title>{xesc(item["title"])}</title>\n{indent}</item>\n')

    def write_manifest_and_settings(self):
        """Writes imsmanifest.xml and course_settings/{module_meta,course_settings,context}.xml
        into build_dir, from whatever modules/resources have been registered
        so far. Call this once, after all modules/items/resources are added."""
        self._resolve_page_links()
        parts = ['<?xml version="1.0" encoding="UTF-8"?>\n']
        parts.append(
            '<manifest identifier="' + gid() + '" '
            'xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" '
            'xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource" '
            'xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1 '
            'http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imscp_v1p2_v1p0.xsd '
            'http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource '
            'http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd '
            'http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest '
            'http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lommanifest_v1p0.xsd">\n'
        )
        parts.append(
            "  <metadata>\n"
            "    <schema>IMS Common Cartridge</schema>\n"
            "    <schemaversion>1.1.0</schemaversion>\n"
            "    <lomimscc:lom>\n"
            "      <lomimscc:general>\n"
            f"        <lomimscc:title><lomimscc:string>{xesc(self.course_title)}</lomimscc:string></lomimscc:title>\n"
            "      </lomimscc:general>\n"
            "      <lomimscc:rights>\n"
            "        <lomimscc:copyrightAndOtherRestrictions><lomimscc:value>yes</lomimscc:value></lomimscc:copyrightAndOtherRestrictions>\n"
            "        <lomimscc:description><lomimscc:string>Private (Copyrighted) - http://en.wikipedia.org/wiki/Copyright</lomimscc:string></lomimscc:description>\n"
            "      </lomimscc:rights>\n"
            "    </lomimscc:lom>\n"
            "  </metadata>\n"
        )
        parts.append('  <organizations>\n    <organization identifier="org_1" structure="rooted-hierarchy">\n      <item identifier="LearningModules">\n')
        for mod in self.modules:
            parts.append(f'        <item identifier="{mod["id"]}">\n          <title>{xesc(mod["title"])}</title>\n')
            for item in mod["items"]:
                parts.append(self._org_item_xml(item, depth=1))
            parts.append("        </item>\n")
        parts.append("      </item>\n    </organization>\n  </organizations>\n")
        # --- THE resource that makes Canvas read course_settings/ at all ---
        # Canvas only treats a package as a Canvas Course Export Package if the
        # manifest DECLARES a resource whose href is
        # course_settings/canvas_export.txt, listing the settings files as its
        # <file> children. Having those files sitting in the zip is not enough:
        # undeclared, Canvas never opens them, so module_meta.xml,
        # assignment_groups.xml, rubrics.xml and every assignment_settings.xml
        # are ignored, assignments import as Pages, and the assignment folders
        # land in course Files as junk.
        #
        # This is what actually caused the assignments-import-as-pages bug, found
        # 2026-08-06 by diffing our manifest against the Spring 2026 Figure
        # Drawing export. Adding canvas_export.txt to the build (the first fix
        # attempted that day) was necessary but NOT sufficient, and the package
        # still imported as plain Common Cartridge until this block existed.
        # Modules kept coming through the whole time only because they are
        # carried by <organizations>, which is standard Common Cartridge.
        # (the <resources> block is appended at the END of this method, once
        # the course_settings/ files below actually exist on disk)

        mm = ['<?xml version="1.0" encoding="UTF-8"?>\n',
              '<modules xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
              'xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">\n']
        for pos, mod in enumerate(self.modules, start=1):
            mm.append(f'  <module identifier="{mod["id"]}">\n')
            mm.append(f'    <title>{xesc(mod["title"])}</title>\n')
            mm.append('    <workflow_state>%s</workflow_state>\n'
                      % self._state(mod["published"]))
            mm.append(f'    <position>{pos}</position>\n')
            mm.append('    <require_sequential_progress>false</require_sequential_progress>\n')
            mm.append('    <locked>false</locked>\n')
            mm.append('    <items>\n')
            for ipos, item in enumerate(mod["items"], start=1):
                mm.append(f'      <item identifier="{item["id"]}">\n')
                mm.append(f'        <content_type>{item["content_type"]}</content_type>\n')
                mm.append('        <workflow_state>%s</workflow_state>\n'
                          % self._state(item["published"]))
                mm.append(f'        <title>{xesc(item["title"])}</title>\n')
                if item["resource_id"]:
                    mm.append(f'        <identifierref>{item["resource_id"]}</identifierref>\n')
                if item.get("url"):
                    mm.append(f'        <url>{xesc(item["url"])}</url>\n')
                mm.append(f'        <position>{ipos}</position>\n')
                mm.append('        <new_tab>%s</new_tab>\n'
                          % ("true" if item.get("new_tab") else "false"))
                mm.append(f'        <indent>{item["indent"]}</indent>\n')
                mm.append('        <link_settings_json>null</link_settings_json>\n')
                mm.append('      </item>\n')
            mm.append('    </items>\n')
            mm.append('  </module>\n')
        mm.append('</modules>\n')
        (self.cs / "module_meta.xml").write_text("".join(mm))

        (self.cs / "course_settings.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<course identifier="{gid()}" xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <title>{xesc(self.course_title)}</title>
  <course_code>{xesc(self.course_title)}</course_code>
  <start_at/>
  <conclude_at/>
  <is_public>false</is_public>
  <is_public_to_auth_users>false</is_public_to_auth_users>
  <allow_student_wiki_edits>false</allow_student_wiki_edits>
  <syllabus_course_summary>true</syllabus_course_summary>
  <default_wiki_editing_roles>teachers</default_wiki_editing_roles>
  <allow_student_organized_groups>false</allow_student_organized_groups>
  <default_view>modules</default_view>
{self._weighting_scheme_xml()}  <license>private</license>
  <indexed>false</indexed>
  <hide_final_grade>false</hide_final_grade>
</course>
""")

        (self.cs / "context.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<context_info xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <course_name>{xesc(self.course_title)}</course_name>
  <root_account_name>{xesc(self.root_account_name)}</root_account_name>
  <canvas_domain>{xesc(self.canvas_domain)}</canvas_domain>
</context_info>
""")

        if getattr(self, "assignment_groups", None):
            ag = ['<?xml version="1.0" encoding="UTF-8"?>\n',
                  '<assignmentGroups xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                  'xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">\n']
            for g in self.assignment_groups:
                ag.append(f'  <assignmentGroup identifier="{g["id"]}">\n')
                ag.append(f'    <title>{xesc(g["title"])}</title>\n')
                ag.append(f'    <position>{g["position"]}</position>\n')
                ag.append(f'    <group_weight>{g["weight"]}</group_weight>\n')
                ag.append('  </assignmentGroup>\n')
            ag.append('</assignmentGroups>\n')
            (self.cs / "assignment_groups.xml").write_text("".join(ag))

        if getattr(self, "rubrics", None):
            rb = ['<?xml version="1.0" encoding="UTF-8"?>\n',
                  '<rubrics xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                  'xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">\n']
            for r in self.rubrics:
                rb.append(f'  <rubric identifier="{r["id"]}">\n')
                rb.append('    <read_only>false</read_only>\n')
                rb.append(f'    <title>{xesc(r["title"])}</title>\n')
                rb.append('    <reusable>false</reusable>\n')
                rb.append('    <public>false</public>\n')
                rb.append(f'    <points_possible>{float(r["points_possible"])}</points_possible>\n')
                rb.append('    <hide_score_total>false</hide_score_total>\n')
                rb.append('    <free_form_criterion_comments>false</free_form_criterion_comments>\n')
                rb.append('    <rating_order>descending</rating_order>\n')
                rb.append('    <criteria>\n')
                for ci, (desc, pts, long_desc, ratings) in enumerate(r["criteria"], start=1):
                    cid = f'{r["id"]}_{ci}'
                    rb.append('      <criterion>\n')
                    rb.append(f'        <criterion_id>{cid}</criterion_id>\n')
                    rb.append(f'        <points>{float(pts)}</points>\n')
                    rb.append(f'        <description>{xesc(desc)}</description>\n')
                    rb.append(f'        <long_description>{xesc(long_desc)}</long_description>\n')
                    rb.append(f'        <criterion_use_range>{"true" if r["use_range"] else "false"}</criterion_use_range>\n')
                    rb.append('        <ratings>\n')
                    for ri, (label, rpts) in enumerate(ratings, start=1):
                        rb.append('          <rating>\n')
                        rb.append(f'            <description>{xesc(label)}</description>\n')
                        rb.append(f'            <points>{float(rpts)}</points>\n')
                        rb.append(f'            <criterion_id>{cid}</criterion_id>\n')
                        rb.append(f'            <id>{cid}_r{ri}</id>\n')
                        rb.append('          </rating>\n')
                    rb.append('        </ratings>\n')
                    rb.append('      </criterion>\n')
                rb.append('    </criteria>\n')
                rb.append('  </rubric>\n')
            rb.append('</rubrics>\n')
            (self.cs / "rubrics.xml").write_text("".join(rb))

        # --- The file that makes Canvas run its OWN importer --------------
        # Canvas decides whether a package is a *Canvas Course Export Package*
        # or a plain IMS Common Cartridge by looking for
        # course_settings/canvas_export.txt. Without it the generic Common
        # Cartridge importer runs, and that importer:
        #   - builds modules and pages from the manifest <organizations> tree
        #     (so modules, subheaders and pages all look fine, which is what
        #     made this so easy to miss),
        #   - but IGNORES assignment_settings.xml and assignment_groups.xml,
        #     so every Assignment silently lands as a Page with no points, no
        #     gradebook column and no submission type,
        #   - and dumps the unrecognised assignment folders, plus a copy of
        #     every wiki_content HTML file, into the course Files area as junk.
        #
        # Found by exporting a live hand-built course back out of
        # Canvas and diffing it against what we built: 11 assignments had
        # become pages, the five weighted assignment groups were gone, and
        # 125 stray files were sitting in Files. The assignment_settings.xml
        # files were correct all along; they were simply never read.
        #
        # Canvas's own exports put a joke in this file. The content is not
        # checked, only the presence, but matching the real thing keeps the
        # package indistinguishable from a genuine Canvas export.
        (self.cs / "canvas_export.txt").write_text(
            "Q: What did the panda say when he was forced out of his natural habitat?\n"
            "A: This is un-BEAR-able\n"
        )

        # Real Canvas exports also carry these two. Canvas tolerates their
        # absence, but they cost nothing and keep the package shaped like a
        # genuine export.
        (self.cs / "files_meta.xml").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<fileMeta xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <folders>
    <folder path="Uploaded Media">
      <hidden>true</hidden>
    </folder>
  </folders>
</fileMeta>
""")
        (self.cs / "media_tracks.xml").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<media_tracks xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
</media_tracks>
""")

        # The dedicated Syllabus page, if one was set. Declared in its own
        # resource with intendeduse="syllabus", and deliberately NOT listed
        # among the course_settings files below, which is exactly how a real
        # Canvas export lays it out.
        syllabus_resource = None
        if getattr(self, "syllabus_html", None) is not None:
            (self.cs / "syllabus.html").write_text(
                self._page_html("Syllabus", self.syllabus_html, gid()))
            syllabus_resource = {
                "id": None, "type": "syllabus",
                "href": "course_settings/syllabus.html",
                "intendeduse": "syllabus",
            }

        settings_files = [f"course_settings/{n}" for n in (
            "course_settings.xml", "module_meta.xml", "assignment_groups.xml",
            "rubrics.xml", "files_meta.xml", "context.xml", "media_tracks.xml",
            "canvas_export.txt",
        ) if (self.cs / n).exists()]
        self.course_settings_resource_id = gid()
        if syllabus_resource:
            # Real exports name it after the course_settings resource, as
            # "<that id>_syllabus". Identifiers are otherwise g + 32 hex and
            # a hand-written one fails silently, so copy the export's shape
            # rather than inventing something readable.
            syllabus_resource["id"] = "%s_syllabus" % self.course_settings_resource_id
        parts.append("  <resources>\n")
        parts.append(self._resource_xml({
            "id": self.course_settings_resource_id, "type": "coursesettings",
            "href": "course_settings/canvas_export.txt",
            "extra_files": settings_files,
        }))
        if syllabus_resource:
            parts.append(self._resource_xml(syllabus_resource))
        for r in self.resources:
            parts.append(self._resource_xml(r))
        parts.append("  </resources>\n</manifest>\n")
        (self.build / "imsmanifest.xml").write_text("".join(parts))

    # -- Validate + zip ------------------------------------------------------

    def validate(self):
        """Run before zipping, every time. Returns (ok: bool, report: str).
        Checks: manifest and module_meta.xml are well-formed XML, every
        module-item identifierref resolves to a declared resource, every
        declared resource's file actually exists on disk. Does NOT check
        the zip itself — call this before zip_package(), then re-run the
        zip-entry cross-check that zip_package() prints after zipping."""
        import xml.etree.ElementTree as ET
        lines = []
        ok = True
        ns = {'cc': 'http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1'}
        try:
            tree = ET.parse(self.build / "imsmanifest.xml")
            ET.parse(self.cs / "module_meta.xml")
            lines.append("XML well-formed: OK")
        except ET.ParseError as e:
            return False, f"XML NOT well-formed: {e}"

        root = tree.getroot()
        resource_ids = {r.get('identifier') for r in root.findall('.//cc:resources/cc:resource', ns)}
        item_refs = {i.get('identifierref') for i in root.findall('.//cc:organizations//cc:item', ns) if i.get('identifierref')}
        missing = item_refs - resource_ids
        lines.append(f"resource ids: {len(resource_ids)} | item refs: {len(item_refs)}")
        if missing:
            ok = False
            lines.append(f"MISSING (item refs with no resource): {missing}")
        else:
            lines.append("MISSING: none")

        # A weblink resource has no href attribute of its own — its file is
        # declared only as a <file> child — so check those separately.
        missing_files = [r.get('href') for r in root.findall('.//cc:resources/cc:resource', ns)
                          if r.get('href') and not (self.build / r.get('href')).exists()]
        missing_files += [f.get('href') for f in root.findall('.//cc:resources/cc:resource/cc:file', ns)
                          if f.get('href') and not (self.build / f.get('href')).exists()]
        # also check assignment resources' extra_files (assignment_settings.xml),
        # which aren't the primary href and so wouldn't otherwise be checked.
        for r in self.resources:
            for extra in r.get("extra_files", []):
                if not (self.build / extra).exists():
                    missing_files.append(extra)
        if missing_files:
            ok = False
            lines.append(f"MISSING FILES on disk: {missing_files}")
        else:
            lines.append("MISSING FILES: none")

        # Canvas-export marker. Without it Canvas runs the generic Common
        # Cartridge importer and every Assignment silently becomes a Page
        # (see the note in write_manifest_and_settings). Nothing downstream
        # fails, the package validates, the modules look right on import,
        # and you only find out by exporting the course back out — so this
        # is a hard failure here rather than a warning.
        n_assignments = sum(1 for r in self.resources if r["type"] == "assignment")
        if not (self.cs / "canvas_export.txt").exists():
            ok = False
            lines.append("canvas_export.txt: MISSING from course_settings/")

        # The file existing is NOT enough — it has to be DECLARED as a resource
        # in the manifest, or Canvas never opens course_settings/ at all. This
        # check exists because shipping the file alone was tried first and the
        # package still imported as plain Common Cartridge.
        declared = [r for r in root.findall('.//cc:resources/cc:resource', ns)
                    if r.get('href') == 'course_settings/canvas_export.txt']
        if not declared:
            ok = False
            lines.append(
                f"COURSE SETTINGS RESOURCE NOT DECLARED in the manifest — Canvas will "
                f"import this as a plain Common Cartridge, turning all {n_assignments} "
                f"assignment(s) into Pages and dropping the assignment groups and rubrics"
            )
        else:
            # Union in every OTHER resource that declares a course_settings
            # file, not just the main one. syllabus.html lives in its own
            # resource with intendeduse="syllabus" and is deliberately absent
            # from the main resource's file list, which is how a real export
            # lays it out — so checking against the main resource alone
            # rejected a correct package and blocked the build.
            declared_files = set()
            for res in root.findall('.//cc:resources/cc:resource', ns):
                for f in res.findall('cc:file', ns):
                    if (f.get('href') or "").startswith("course_settings/"):
                        declared_files.add(f.get('href'))
                if (res.get('href') or "").startswith("course_settings/"):
                    declared_files.add(res.get('href'))
            on_disk = {f"course_settings/{p.name}" for p in self.cs.iterdir() if p.is_file()}
            undeclared = on_disk - declared_files
            if undeclared:
                ok = False
                lines.append(f"course_settings files present but NOT declared: {sorted(undeclared)}")
            else:
                lines.append(f"course settings resource: declared, {len(declared_files)} files "
                             f"(assignments: {n_assignments})")

        # Rubrics: every rubric_identifierref must resolve, and each rubric's
        # criteria must sum to its stated points_possible, or the gradebook
        # column and the rubric disagree on the total.
        rubrics = getattr(self, "rubrics", None) or []
        if rubrics:
            declared = {r["id"] for r in rubrics}
            dangling = {r["rubric_id"] for r in self.resources
                        if r.get("rubric_id") and r["rubric_id"] not in declared}
            bad_totals = [f'{r["title"]} ({sum(c[1] for c in r["criteria"])} vs {r["points_possible"]})'
                          for r in rubrics
                          if abs(sum(c[1] for c in r["criteria"]) - r["points_possible"]) > 1e-6]
            bad_ratings = [f'{r["title"]}/{c[0]}' for r in rubrics for c in r["criteria"]
                           if c[3] and abs(max(p for _, p in c[3]) - c[1]) > 1e-6]
            if dangling:
                ok = False; lines.append(f"RUBRIC refs with no rubric declared: {dangling}")
            if bad_totals:
                ok = False; lines.append(f"RUBRIC criteria don't sum to points_possible: {bad_totals}")
            if bad_ratings:
                ok = False; lines.append(f"RUBRIC top rating != criterion points: {bad_ratings}")
            if not (dangling or bad_totals or bad_ratings):
                attached = sum(1 for r in self.resources if r.get("rubric_id"))
                lines.append(f"rubrics: {len(rubrics)} declared, attached to {attached} assignment(s)")

        # Assignment groups must be declared, and their weights must sum to
        # 100 if any weight is set at all, or Canvas silently reweights.
        groups = getattr(self, "assignment_groups", None) or []
        if n_assignments and not groups and self.external_assignment_groups:
            lines.append(
                f"assignment groups: none declared, by request. "
                f"{n_assignments} assignment(s) name a group by identifier and "
                f"CANVAS WILL IGNORE IT: tested 2026-09-05, every one lands in "
                f"a new group called 'Imported Assignments' and has to be moved "
                f"by hand. This is still the better option -- shipping the "
                f"groups risks duplicating them and reweighting the gradebook")
        elif n_assignments and not groups:
            ok = False
            lines.append(f"ASSIGNMENT GROUPS: none declared but {n_assignments} assignment(s) exist")
        elif groups:
            total = sum(g["weight"] for g in groups)
            if any(g["weight"] for g in groups) and abs(total - 100) > 1e-6:
                ok = False
                lines.append(f"ASSIGNMENT GROUP WEIGHTS sum to {total}, expected 100")
            else:
                lines.append(f"assignment groups: {len(groups)}, weights sum to {total}")

        return ok, "\n".join(lines)

    def zip_package(self, out_path):
        """Zip build_dir's imsmanifest.xml/wiki_content/web_resources/course_settings
        (plus any Assignment folders, which live at build_dir root, one per
        assignment resource id) into out_path, then cross-check every manifest
        href against the ACTUAL zip entries (not just the filesystem) — this
        is the check that catches encoding mismatches between what the
        manifest says and what's really inside the archive. Returns (out_path, report)."""
        import xml.etree.ElementTree as ET
        out_path = pathlib.Path(out_path)
        if out_path.exists():
            out_path.unlink()
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(self.build / "imsmanifest.xml", "imsmanifest.xml")
            for folder in ("wiki_content", "web_resources", "course_settings"):
                base = self.build / folder
                for f in base.rglob("*"):
                    if f.is_file():
                        z.write(f, str(pathlib.Path(folder) / f.relative_to(base)))
            for r in self.resources:
                if r["type"] == "weblink":
                    z.write(self.build / r["href"], r["href"])
                    continue
                if r["type"] != "assignment":
                    continue
                for rel in [r["href"], *r.get("extra_files", [])]:
                    z.write(self.build / rel, rel)

        ns = {'cc': 'http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1'}
        tree = ET.parse(self.build / "imsmanifest.xml")
        hrefs = {r.get('href') for r in tree.getroot().findall('.//cc:resources/cc:resource', ns)}
        hrefs.discard(None)   # weblink resources carry no href attribute
        with zipfile.ZipFile(out_path) as z:
            names = set(z.namelist())
        missing = [h for h in hrefs if h not in names]

        # And the other direction. This check only ever asked whether every
        # declared href made it into the zip, which passes clean on a package
        # carrying files nobody declared. add_page_resource() renames rather
        # than overwrites when the filename is taken, so building twice into
        # the same directory leaves aquatint-2.html beside aquatint.html; the
        # manifest points only at the new one, and the loop above zips whole
        # folders, so the stale copy rides along. One package shipped 193
        # entries against 79 resources that way, validated clean, and imported
        # ~110 files into the course's Files area that had to be deleted by
        # hand, one checkbox at a time.
        #
        # A hard failure, not a warning. The fix is one line in the build
        # script -- shutil.rmtree(build_dir) before constructing the builder --
        # and a warning here would be read past.
        declared = set(hrefs)
        for r in tree.getroot().findall('.//cc:resources/cc:resource', ns):
            for f in r.findall('cc:file', ns):
                declared.add(f.get('href'))
        declared.add("imsmanifest.xml")
        orphans = sorted(n for n in names
                         if not n.endswith("/")
                         and html.unescape(n) not in {html.unescape(d) for d in declared if d})
        if orphans:
            raise ValueError(
                "%d file(s) in the build directory are declared by no resource, so they "
                "would import into Canvas as Files nobody asked for. This is almost always "
                "a stale build directory: rmtree it before building. Orphans:\n  %s"
                % (len(orphans), "\n  ".join(orphans[:20])
                   + ("\n  ... and %d more" % (len(orphans) - 20) if len(orphans) > 20 else "")))

        report = f"Resources: {len(hrefs)} | Missing from zip: {missing or 'none'}"
        return out_path, report

    # -- Preview before import ------------------------------------------------
    #
    # No local preview generator here. Use Instructure's own viewer;
    # https://common-cartridge-viewer.netlify.app/ (Instructure's own
    # open-source viewer) renders the real module/item tree, including
    # indent structure, straight from a .imscc, more faithfully than a
    # hand-rolled HTML mirror ever did. That's the trusted verification
    # step before import now — see docs/canvas-imscc-playbook.md.
