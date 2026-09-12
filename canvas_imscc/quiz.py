"""Canvas Classic Quiz questions, as QTI 1.2.

Every shape here was derived from real Canvas exports, not from the QTI spec:
Michael Diaz's own University of Tampa export (essay, multiple choice,
true/false) and the commonsyllabi corpus (short answer, multiple answers). The
spec allows a great deal that Canvas does not read, and Canvas reads a few
things the spec does not mention, so the exports are the authority.

THE THING THAT SURPRISES EVERYONE: a Canvas course export writes each quiz
TWICE.

  <rid>/assessment_qti.xml              Common Cartridge profile. Its
                                        <section> is EMPTY. No questions.
  non_cc_assessments/<rid>.xml.qti      Canvas's own. THIS has the questions.

Both real exports and Michael's do exactly this: 0 items in the CC file, all
items in the non-CC one. The CC file is a compatibility shell so that a
non-Canvas LMS sees *an* assessment; Canvas itself reads the other. Write only
the CC file and you get an empty quiz with no error.

(Note that courseforge does the opposite, putting questions in the CC file. It
may well also import; this kit follows what Canvas itself produces.)

New Quizzes are not this format at all. They are LTI-based, and a QTI-only
export of a course containing only New Quizzes comes back with an empty
<resources> element, which is what happens in practice and looks like a broken
export. Everything here is Classic Quizzes.
"""

import html as _html
import uuid

__all__ = ["multiple_choice", "true_false", "essay", "short_answer",
           "multiple_answers", "QUESTION_TYPES"]

QUESTION_TYPES = ("multiple_choice_question", "true_false_question",
                  "essay_question", "short_answer_question",
                  "multiple_answers_question")


def _esc(s):
    return _html.escape(s, quote=True)


def _aid():
    """Answer identifier. Canvas writes UUIDs in current exports and small
    integers in older ones; both come back in, so the value only has to be
    unique and stable within the question."""
    return str(uuid.uuid4())


def _html_material(body_html, indent):
    return ('%s<material>\n%s  <mattext texttype="text/html">%s</mattext>\n'
            '%s</material>\n' % (indent, indent, _esc(body_html), indent))


def _question(qtype, text, points, answer_ids=()):
    """Common front half of every item: metadata plus the prompt."""
    return {
        "type": qtype,
        "text": text,
        "points": float(points),
        "answer_ids": list(answer_ids),
        "aq_ref": uuid.uuid4().hex,
    }


# -- the five constructors -------------------------------------------------

def multiple_choice(text, choices, points=1.0):
    """choices: [(html, is_correct), ...]. Exactly one must be correct."""
    correct = [i for i, (_, ok) in enumerate(choices) if ok]
    if len(correct) != 1:
        raise ValueError(
            "multiple_choice needs exactly one correct choice, got %d. Use "
            "multiple_answers() for a select-all-that-apply question."
            % len(correct))
    if len(choices) < 2:
        raise ValueError("multiple_choice needs at least two choices")
    ids = [_aid() for _ in choices]
    q = _question("multiple_choice_question", text, points, ids)
    q["choices"] = [(ids[i], h, ok) for i, (h, ok) in enumerate(choices)]
    return q


def multiple_answers(text, choices, points=1.0):
    """choices: [(html, is_correct), ...]. One or more correct. Canvas scores
    it all-or-nothing: every correct box ticked AND every wrong one clear."""
    if not any(ok for _, ok in choices):
        raise ValueError("multiple_answers needs at least one correct choice")
    if len(choices) < 2:
        raise ValueError("multiple_answers needs at least two choices")
    ids = [_aid() for _ in choices]
    q = _question("multiple_answers_question", text, points, ids)
    q["choices"] = [(ids[i], h, ok) for i, (h, ok) in enumerate(choices)]
    return q


def true_false(text, answer, points=1.0):
    """answer: True or False. The choice identifiers are the fixed strings
    true_choice / false_choice, which is what Canvas writes."""
    if answer not in (True, False):
        raise ValueError("true_false answer must be True or False, got %r" % (answer,))
    q = _question("true_false_question", text, points,
                  ["true_choice", "false_choice"])
    q["answer"] = answer
    return q


def essay(text, points=1.0):
    """Free text, graded by hand. No respcondition, so Canvas leaves it
    ungraded until someone reads it."""
    return _question("essay_question", text, points)


def short_answer(text, accepted, points=1.0):
    """accepted: list of strings Canvas will accept, compared case-sensitively
    as separate <varequal> entries. Include the capitalised and lowercase forms
    if you want both, which is exactly what the real exports do."""
    accepted = [a for a in accepted if a != ""]
    if not accepted:
        raise ValueError("short_answer needs at least one accepted answer")
    q = _question("short_answer_question", text, points)
    q["accepted"] = list(accepted)
    return q


# -- rendering -------------------------------------------------------------

def _metadata_xml(q, ind):
    # Field list and ORDER both copied from a current Canvas export. The last
    # three are what a hand-written generator leaves out: Canvas writes them on
    # every item, so the kit does too.
    fields = [("question_type", q["type"]),
              ("points_possible", "%g" % q["points"] if q["points"] % 1 else
               "%.1f" % q["points"]),
              ("original_answer_ids", ",".join(q["answer_ids"])),
              # Canvas keys every quiz question to an underlying
              # assessment_question. There is no question bank here, so this is
              # just a stable unique id per question.
              ("assessment_question_identifierref", q["aq_ref"]),
              ("calculator_type", "none")]
    if q["type"] == "essay_question":
        fields.append(("grading_notes", ""))
    out = ["%s<itemmetadata>\n%s  <qtimetadata>\n" % (ind, ind)]
    for label, entry in fields:
        out.append("%s    <qtimetadatafield>\n"
                   "%s      <fieldlabel>%s</fieldlabel>\n"
                   "%s      <fieldentry>%s</fieldentry>\n"
                   "%s    </qtimetadatafield>\n"
                   % (ind, ind, label, ind, _esc(entry), ind))
    out.append("%s  </qtimetadata>\n%s</itemmetadata>\n" % (ind, ind))
    return "".join(out)


def _choice_presentation(q, ind, cardinality):
    out = ["%s<presentation>\n" % ind]
    out.append(_html_material(q["text"], ind + "  "))
    out.append('%s  <response_lid ident="response1" rcardinality="%s">\n'
               '%s    <render_choice>\n' % (ind, cardinality, ind))
    for cid, chtml, _ok in q["choices"]:
        out.append('%s      <response_label ident="%s">\n' % (ind, _esc(cid)))
        out.append(_html_material(chtml, ind + "        "))
        out.append("%s      </response_label>\n" % ind)
    out.append("%s    </render_choice>\n%s  </response_lid>\n%s</presentation>\n"
               % (ind, ind, ind))
    return "".join(out)


def _outcomes(ind):
    return ('%s  <outcomes>\n'
            '%s    <decvar maxvalue="100" minvalue="0" varname="SCORE" vartype="Decimal"/>\n'
            '%s  </outcomes>\n' % (ind, ind, ind))


def _item_xml(q, ident, title, ind="      "):
    out = ['%s<item ident="%s" title="%s">\n' % (ind, ident, _esc(title))]
    out.append(_metadata_xml(q, ind + "  "))
    t = q["type"]

    if t in ("multiple_choice_question", "multiple_answers_question"):
        card = "Single" if t == "multiple_choice_question" else "Multiple"
        out.append(_choice_presentation(q, ind + "  ", card))
        out.append("%s  <resprocessing>\n" % ind)
        out.append(_outcomes(ind + "  "))
        out.append('%s    <respcondition continue="No">\n'
                   '%s      <conditionvar>\n' % (ind, ind))
        if t == "multiple_choice_question":
            cid = next(c for c, _h, ok in q["choices"] if ok)
            out.append('%s        <varequal respident="response1">%s</varequal>\n'
                       % (ind, _esc(cid)))
        else:
            # All-or-nothing: every wrong choice negated, every right one
            # required, inside a single <and>. Straight from a real export.
            out.append("%s        <and>\n" % ind)
            for cid, _h, ok in q["choices"]:
                if not ok:
                    out.append('%s          <not>\n'
                               '%s            <varequal respident="response1">%s</varequal>\n'
                               '%s          </not>\n' % (ind, ind, _esc(cid), ind))
            for cid, _h, ok in q["choices"]:
                if ok:
                    out.append('%s          <varequal respident="response1">%s</varequal>\n'
                               % (ind, _esc(cid)))
            out.append("%s        </and>\n" % ind)
        out.append('%s      </conditionvar>\n'
                   '%s      <setvar action="Set" varname="SCORE">100</setvar>\n'
                   '%s    </respcondition>\n%s  </resprocessing>\n'
                   % (ind, ind, ind, ind))

    elif t == "true_false_question":
        q2 = dict(q, choices=[("true_choice", "True", q["answer"] is True),
                              ("false_choice", "False", q["answer"] is False)])
        # True/False labels are plain text in a real export, not wrapped in <p>.
        out.append("%s  <presentation>\n" % ind)
        out.append(_html_material(q["text"], ind + "    "))
        out.append('%s    <response_lid ident="response1" rcardinality="Single">\n'
                   '%s      <render_choice>\n' % (ind, ind))
        for cid, label, _ok in q2["choices"]:
            out.append('%s        <response_label ident="%s">\n'
                       '%s          <material>\n'
                       '%s            <mattext texttype="text/html">%s</mattext>\n'
                       '%s          </material>\n'
                       '%s        </response_label>\n'
                       % (ind, cid, ind, ind, label, ind, ind))
        out.append("%s      </render_choice>\n%s    </response_lid>\n"
                   "%s  </presentation>\n" % (ind, ind, ind))
        out.append("%s  <resprocessing>\n" % ind)
        out.append(_outcomes(ind + "  "))
        out.append('%s    <respcondition continue="No">\n'
                   '%s      <conditionvar>\n'
                   '%s        <varequal respident="response1">%s</varequal>\n'
                   '%s      </conditionvar>\n'
                   '%s      <setvar action="Set" varname="SCORE">100</setvar>\n'
                   '%s    </respcondition>\n%s  </resprocessing>\n'
                   % (ind, ind, ind,
                      "true_choice" if q["answer"] else "false_choice",
                      ind, ind, ind, ind))

    elif t in ("essay_question", "short_answer_question"):
        out.append("%s  <presentation>\n" % ind)
        out.append(_html_material(q["text"], ind + "    "))
        extra = (' rce="Yes" word_count="No" spell_check="No" word_limit_enabled="No"'
                 if t == "essay_question" else "")
        out.append('%s    <response_str ident="response1" rcardinality="Single"%s>\n'
                   '%s      <render_fib>\n'
                   '%s        <response_label ident="answer1" rshuffle="No"/>\n'
                   '%s      </render_fib>\n'
                   '%s    </response_str>\n'
                   '%s  </presentation>\n'
                   % (ind, extra, ind, ind, ind, ind, ind))
        out.append("%s  <resprocessing>\n" % ind)
        out.append(_outcomes(ind + "  "))
        out.append('%s    <respcondition continue="No">\n'
                   '%s      <conditionvar>\n' % (ind, ind))
        if t == "essay_question":
            # No correct answer to match, so Canvas parks it for manual grading.
            out.append("%s        <other/>\n" % ind)
            out.append('%s      </conditionvar>\n%s    </respcondition>\n' % (ind, ind))
        else:
            for a in q["accepted"]:
                out.append('%s        <varequal respident="response1">%s</varequal>\n'
                           % (ind, _esc(a)))
            out.append('%s      </conditionvar>\n'
                       '%s      <setvar action="Set" varname="SCORE">100</setvar>\n'
                       '%s    </respcondition>\n' % (ind, ind, ind))
        out.append("%s  </resprocessing>\n" % ind)
    else:
        raise ValueError("unsupported question type: %r" % t)

    out.append("%s</item>\n" % ind)
    return "".join(out)
