"""Literal, single-pass placeholders for performer confirmation scripts."""
import re


DEFAULT_TEMPLATE = ('Confirmed for @pdates. Will send over the gig sheets now. '
                    'Please make sure all of the details are correct before signing. Thank you!')
TEMPLATE_FIELDS = (
    ('@performer', 'Performer name'),
    ('@pdates', 'This performer’s confirmed dates'),
    ('@dates', 'All open dates in this schedule'),
    ('@count', 'This performer’s number of gigs'),
    ('@schedule', 'Schedule name'),
    ('@notes', 'Schedule notes'),
)
SCHEDULE_TEMPLATE_FIELDS = (
    ('@schedule', 'Schedule name'),
    ('@dates', 'All open dates in this schedule'),
    ('@count', 'Total booked dates in this schedule'),
    ('@notes', 'Existing schedule notes'),
)


def format_dates(dates):
    return ', '.join(f'{date.month}/{date.day}/{date.year}' for date in sorted(dates))


def _render_fields(template, values):
    return re.sub(r'@@|(?<![\w@])@([A-Za-z][A-Za-z0-9_]*)',
                  lambda match: '@' if match[0] == '@@' else values.get(match[1], match[0]), template)


def render_schedule_template(template, *, open_dates, schedule, notes, booked_count):
    return _render_fields(template, dict(dates=format_dates(open_dates), schedule=schedule,
                                        notes=notes, count=str(booked_count)))


def render_confirmation(template, *, performer, confirmed_dates, open_dates, schedule, notes):
    if not template.strip():
        template = DEFAULT_TEMPLATE
    values = dict(performer=performer, pdates=format_dates(confirmed_dates),
                  dates=format_dates(open_dates), count=str(len(confirmed_dates)),
                  schedule=schedule, notes=notes)
    # Do not evaluate expressions or recursively expand tokens in user data.
    # @@ provides a literal @; unknown fields and email addresses remain intact.
    return _render_fields(template, values)
