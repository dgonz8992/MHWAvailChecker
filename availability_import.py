"""Read pasted booking availability without treating uncertain text as confirmed dates.

This is a deterministic English/US-date parser. Import results include review notes;
callers should show those notes before applying a large or partially parsed import.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re

MONTH_NAMES = ('January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December')
MONTHS = {name.lower(): number for number, name in enumerate(MONTH_NAMES, 1)}
MONTHS.update({name[:3].lower(): number for number, name in enumerate(MONTH_NAMES, 1)})
MONTHS.update({'sept': 9, 'febuary': 2})
MONTH_PATTERN = r'(?<![a-z])(?:' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + r')(?![a-z])\.?'
MONTH_RE = re.compile(MONTH_PATTERN, re.I)
DAY = r'\d{1,2}(?:st|nd|rd|th)?'
# Full numeric dates come before bare days. A slash year must have 2 or 4 digits.
NUMERIC = (r'(?<![\w/])(?P<month>\d{1,2})\s*(?P<separator>[/.:\-])\s*'
           r'(?P<day>\d{1,2})(?:st|nd|rd|th)?'
           r'(?:\s*/\s*(?P<year>\d{4}|\d{2})(?!\d))?(?!\d)')
TOKEN_RE = re.compile(
    r'(?P<reverse>\b' + DAY + r'\s+(?:of\s+)?(?:' + MONTH_PATTERN + r'))'
    r'|(?P<numeric>' + NUMERIC + r')'
    r'|(?P<month_name>' + MONTH_PATTERN + r')'
    r'|(?P<bare>\b\d{1,4}(?:st|nd|rd|th)?\b)', re.I)
EXCEPT_RE = re.compile(r'\b(?:except(?:\s+for)?|besides|excluding|but\s+not)\b', re.I)
ALL_RE = re.compile(r'\b(?:all|every|any|everything)\b', re.I)
WEEKDAYS = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6}
WEEKDAY_RE = re.compile(r'\b(' + '|'.join(WEEKDAYS) + r")(?:s|'s)?\b", re.I)
NOTE_RE = re.compile(r'^(?:bin\s*\d+\b|shed\b|vetted good fits\b|potential good fits\b)', re.I)
TIME_RE = re.compile(r'\b\d{1,2}:\d{2}\s*(?:am|pm)\b', re.I)
SUPPLIED_RE = re.compile(r'\b(?:supplied|listed|provided)\b', re.I)
WRITTEN_YEAR_RE = re.compile(r'(?<![\d/])([1-9]\d{3})(?!\d)')


@dataclass
class ImportResult:
    availability: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def preview(self):
        lines = []
        for name, dates in self.availability.items():
            lines.append(f'{name} — {len(dates)} dates')
            lines.append(', '.join(date.strftime('%m/%d/%Y') for date in dates) or '(No available open dates)')
            lines.append('')
        if self.notes:
            lines.append('REVIEW NOTES / SKIPPED ENTRIES')
            lines.extend('• ' + note for note in self.notes)
        return '\n'.join(lines)


def calendar_date(month, day, year, start_month, explicit_year=None):
    if not 1 <= year <= 9998 or not 1 <= start_month <= 12:
        raise ValueError('Use a year from 1–9998 and a start month from 1–12.')
    target_year = year + (month < start_month)
    if explicit_year is not None:
        target_year = int(explicit_year)
        if len(str(explicit_year)) == 2:
            target_year += 2000
    try:
        return datetime(target_year, month, day)
    except (ValueError, OverflowError):
        raise ValueError(f'Invalid date {month}/{day}/{target_year}.') from None


def _clean(text):
    text = text.replace('’', "'").replace('‘', "'")
    text = text.replace('“', '"').replace('”', '"')
    text = re.sub('(' + MONTH_PATTERN + r")\s*'(\d{2})\b",
                  lambda match: match[1] + ' 20' + match[2], text, flags=re.I)
    text = re.sub(r'(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)',
                  lambda match: f'{match[2]}/{match[3]}/{match[1]}', text)
    text = re.sub(r'(?<!\d)(\d{1,2})[-.](\d{1,2})[-.](\d{4})(?!\d)',
                  lambda match: f'{match[1]}/{match[2]}/{match[3]}', text)
    text = TIME_RE.sub(' ', text)
    text = re.sub(r'\$\s*\d+(?:,\d{3})*(?:\.\d{2})?', ' ', text)
    # Spaced slashes in written-month lists separate days/month sections.
    if MONTH_RE.search(text):
        text = re.sub(r'\s+/\s+', ', ', text)
    text = re.sub('(' + MONTH_PATTERN + r'\s+' + DAY + r')\s*-\s*(' + DAY + r')(?!\d|/)',
                  r'\1–\2', text, flags=re.I)
    # Some people type a day as a word in an otherwise numeric date.
    words = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
             'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
    text = re.sub(r'(?<=/)\s*(' + '|'.join(words) + r')\b',
                  lambda match: str(words[match.group(1).lower()]), text, flags=re.I)
    return text


class DateReader:
    """Carry a written/shared month across consecutive lines of one performer."""
    def __init__(self, year, start_month, default_year=None):
        calendar_date(1, 1, year, start_month)
        self.year, self.start_month = year, start_month
        self.month = None
        self.explicit_year = None
        self.default_year = default_year
        self.notes = []

    def read(self, text):
        text = _clean(text)
        tentative = re.findall(r'\(\s*maybe[^)]*\)', text, re.I)
        if tentative:
            self.notes.append('Tentative date omitted: ' + ', '.join(tentative))
            text = re.sub(r'\(\s*maybe[^)]*\)', ' ', text, flags=re.I)
        if re.search(r'\bmaybe\b', text, re.I):
            self.notes.append('Tentative line omitted: ' + text.strip())
            return set()
        # Named holidays have a known day; bare "new years" does not specify Eve/Day.
        if re.search(r'\bnew\s+year', text, re.I):
            if not re.search(r"\bnew\s+year(?:'s|s)?\s+(?:day|eve)\b", text, re.I):
                raise ValueError('"new years" is ambiguous. Specify New Year\'s Day or New Year\'s Eve.')
        text = re.sub(r"\bnew\s+year(?:'s|s)?\s+day\b", '1/1', text, flags=re.I)
        text = re.sub(r"\bnew\s+year(?:'s|s)?\s+eve\b", '12/31', text, flags=re.I)
        text = re.sub(r'\bchristmas(?:\s+day)?\b', '12/25', text, flags=re.I)
        if NOTE_RE.match(text.strip()):
            return set()
        # "12" followed by day lines is a common abbreviated month heading.
        if self.month is None and re.fullmatch(r'\s*\d{1,2}\s*:?\s*', text):
            number = int(re.search(r'\d+', text).group())
            if 1 <= number <= 12:
                self.month = number
                self.notes.append(f'Interpreted standalone {number} as a {MONTH_NAMES[number - 1]} heading.')
                return set()
        events = []
        previous_end = None
        month_seen = False
        month_start = 0
        for token in TOKEN_RE.finditer(text):
            if token.group('month_name'):
                self.month = MONTHS[token.group('month_name').strip('.').lower()]
                self.explicit_year = self.default_year
                month_seen = True
                month_start = len(events)
                previous_end = token.end()
                continue
            explicit = False
            if token.group('reverse'):
                month_match = MONTH_RE.search(token.group())
                self.month = MONTHS[month_match.group().strip('.').lower()]
                day = int(re.match(r'\d+', token.group()).group())
                self.explicit_year = self.default_year
                month_start = len(events)
            elif token.group('numeric'):
                self.month = int(token.group('month'))
                day = int(token.group('day'))
                self.explicit_year = token.group('year')
                explicit = self.explicit_year is not None
            else:
                value = re.match(r'\d+', token.group()).group()
                if len(value) == 4:
                    self.explicit_year = value
                    # A trailing written year qualifies dates in this month section.
                    for index in range(month_start, len(events)):
                        date, begin, end, is_explicit = events[index]
                        if not is_explicit:
                            date = calendar_date(date.month, date.day, self.year, self.start_month, value)
                            events[index] = (date, begin, end, False)
                    previous_end = token.end()
                    continue
                if self.month is None:
                    continue
                gap = text[previous_end:token.start()] if previous_end is not None else text[:token.start()]
                # A day continuation may contain conjunctions and ordinal decoration,
                # but random numbers in prose ("Bin 47", rates, timestamps) aren't days.
                residue = re.sub(r'\b(?:and|or|the|on|of|yes|available|availability|free)\b|[\s,:;&/()\[\]{}=|+→\-–—]', '', gap, flags=re.I)
                if residue:
                    continue
                day = int(value)
            date = calendar_date(self.month, day, self.year, self.start_month, self.explicit_year or self.default_year)
            events.append((date, token.start(), token.end(), explicit))
            previous_end = token.end()
            month_seen = False
        if re.search(r'\d\s*/\s*[a-z]+', MONTH_RE.sub(' ', text), re.I):
            raise ValueError('Unrecognized day after "/". Use a number, for example 2/1.')
        dates = set()
        # Three or more full dates joined with dashes are a list, rather than a range.
        connectors = [bool(re.fullmatch(r'\s*(?:[-–—]|to|through|thru)\s*', MONTH_RE.sub(' ', text[a[2]:b[1]]), re.I))
                      for a, b in zip(events, events[1:])]
        chained = {index for index in range(len(connectors) - 1) if connectors[index] and connectors[index + 1]}
        if chained:
            self.notes.append('Dash-separated date chain treated as listed dates, not a continuous range: ' + text.strip())
        for index, event in enumerate(events):
            date = event[0]
            dates.add(date)
            if index and connectors[index - 1]:
                in_chain = any(index - 1 in (start, start + 1) for start in chained)
                if not in_chain:
                    begin = events[index - 1][0]
                    if date < begin:
                        raise ValueError('Date range ends before it starts: ' + text.strip())
                    if (date - begin).days > 366:
                        raise ValueError('Date range is longer than one year: ' + text.strip())
                    dates.update(begin + timedelta(days=offset) for offset in range((date - begin).days + 1))
        return dates


def extract_dates(text, year, start_month):
    reader = DateReader(year, start_month)
    dates = set()
    for line in text.splitlines():
        dates.update(reader.read(line))
    return sorted(dates)


def _is_bare_name(line):
    if NOTE_RE.match(line) or re.search(r'[.!?:✅]|\b\d', line):
        return False
    if MONTH_RE.search(line) or ALL_RE.search(line) or WEEKDAY_RE.search(line):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", line)
    return bool(words) and len(words) <= 8 and all(word[0].isupper() or word.lower() in ('the', 'and') for word in words)


def _split_blocks(text):
    blocks, current = [], None
    for number, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r'^[•*]\s*', '', raw.strip())
        if not line:
            continue
        if re.search(r'\bscript\b', line, re.I):
            current = None
            continue
        header = re.fullmatch(r'(.+?)\s+[-–—]\s*(.*)', line)
        candidate = header.group(1) if header else ''
        date_prefix = (re.search(r'\d\s*[/.:\-]', candidate)
                       or (MONTH_RE.search(candidate) and re.search(r'\d', candidate))
                       or MONTH_RE.fullmatch(candidate))
        if header and re.search(r'[A-Za-z]', candidate) and not date_prefix:
            name, value = header.groups()
            name = re.sub(r'\s*\(give all\)', '', name, flags=re.I).strip()
            current = (name, number, [])
            blocks.append(current)
            if value:
                current[2].append((number, value))
        elif _is_bare_name(line):
            current = (line, number, [])
            blocks.append(current)
        elif current is not None:
            current[2].append((number, line))
        elif not NOTE_RE.match(line):
            blocks.append(('', number, [(number, line)]))
    return blocks


def _weekdays(text):
    days = {WEEKDAYS[match.group(1).lower()] for match in WEEKDAY_RE.finditer(text)}
    if re.search(r'\bweekends?\b', text, re.I):
        days.update((5, 6))
    if re.search(r'\bweekdays?\b', text, re.I):
        days.update(range(5))
    return days


def _prepare_clauses(lines):
    """Keep negative qualifications out of the positive date/year reader."""
    positive, blocked_years, notes = [], set(), []
    for number, raw in lines:
        clauses = re.split(r'(?<=[.;])\s*(?=(?:no\s+availability|unavailable|the\s+other)\b)',
                           _clean(raw), flags=re.I)
        for clause in clauses:
            clause = clause.strip().strip('"')
            no_year = re.fullmatch(r'no\s+availability\s+in\s+([1-9]\d{3})[.! ]*', clause, re.I)
            if no_year:
                blocked_years.add(int(no_year[1]))
            elif (re.fullmatch(r"the\s+other\s+(?:[1-9]\d{3}\s+)?(?:supplied\s+)?dates?\s+(?:don't|do\s+not)\s+work[.! ]*", clause, re.I)
                  or re.fullmatch(r'unavailable\s*:\s*all\s+other\s+(?:supplied\s+)?(?:' + MONTH_PATTERN + r'\s+)?dates?[.! ]*', clause, re.I)):
                notes.append('Only the positively listed dates were included; other supplied dates were excluded.')
            elif re.match(r'no\s+availability\b|the\s+other\b', clause, re.I):
                raise ValueError(f'Line {number}: Unclear negative qualification: {clause}')
            elif clause:
                positive.append((number, clause))
    return positive, blocked_years, notes


def _parse_block(lines, year, start_month, open_dates):
    lines, blocked_years, clause_notes = _prepare_clauses(lines)
    declared_years = set(WRITTEN_YEAR_RE.findall(' '.join(text for _, text in lines)))
    default_year = next(iter(declared_years)) if len(declared_years) == 1 else None
    reader = DateReader(year, start_month, default_year)
    reader.notes.extend(clause_notes)
    result, exclusions = set(), set()
    using_rule = False
    except_mode = False
    exception_has_dates = False
    needs_exception = False
    check_mode = any('✅' in text for _, text in lines)
    if check_mode:
        reader.notes.append('Only dates with ✅ were included; unchecked dates were omitted.')
    for number, text in lines:
        text = text.strip().lstrip('-•*').strip()
        if NOTE_RE.match(text):
            continue
        try:
            if check_mode:
                if '✅' in text and re.search(r'\d', text):
                    result.update(reader.read(text))
                continue
            if re.search(r"\b(?:unavailable|not\s+available|not\s+free|cannot|can't)\b", text, re.I):
                raise ValueError('Negative availability needs clarification. Use All except followed by unavailable dates.')
            if MONTH_RE.match(text):
                except_mode = False
            parts = EXCEPT_RE.split(text, maxsplit=1)
            base = parts[0]
            exception = parts[1] if len(parts) == 2 else None
            days = _weekdays(base)
            base_dates = reader.read(base)
            # A closing phrase such as "all 2027" or "all good" qualifies an
            # explicit list; it does not turn that list into universal availability.
            mentions_all = bool(ALL_RE.search(base)) and not base_dates
            recurring = bool(days) and (ALL_RE.search(base) or re.search(r'\beach\b', base, re.I) or not base_dates)
            supplied = bool(SUPPLIED_RE.search(base))
            if mentions_all or recurring:
                if mentions_all and not recurring:
                    remainder = MONTH_RE.sub(' ', base)
                    remainder = WRITTEN_YEAR_RE.sub(' ', remainder)
                    remainder = re.sub(r"\bi'?m\b", ' ', remainder, flags=re.I)
                    remainder = re.sub(r"\b(?:i|can|do|available|availability|free|open|for|on|of|all|every|any|everything|these|those|the|dates?|and|in|am|please|to|supplied|listed|provided|you|works?|me|one|two|three|four|five|six|seven|eight|nine|ten)\b|[\s,:.!'\-]", '', remainder, flags=re.I)
                    if remainder:
                        raise ValueError('Unrecognized availability rule: ' + base.strip())
                if not open_dates:
                    raise ValueError('Enter open dates in the main window before importing All, month, or weekday rules.')
                using_rule = True
                months = {MONTHS[match.group().strip('.').lower()] for match in MONTH_RE.finditer(base)}
                years = {int(value) for value in WRITTEN_YEAR_RE.findall(base)}
                if not years and default_year:
                    years = {int(default_year)}
                selected = {date for date in open_dates if (not months or date.month in months)
                            and (not years or date.year in years)
                            and (not recurring or date.weekday() in days)}
                count_words = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                               'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
                claimed_count = re.search(r'\ball\s+(' + '|'.join(count_words) + r')\b', base, re.I)
                if claimed_count and len(selected) != count_words[claimed_count[1].lower()]:
                    reader.notes.append(f'Rule says {claimed_count[1]} supplied dates, but {len(selected)} open dates match; review this selection.')
                result.update(selected)
                result.update(base_dates)
                except_mode = exception is not None
                if exception is not None:
                    needs_exception = True
                    parsed = reader.read(exception)
                    exclusions.update(parsed)
                    exception_has_dates = exception_has_dates or bool(parsed)
                continue
            if exception is not None:
                raise ValueError('An exclusion needs an availability rule, such as All except 12/4.')
            if supplied:
                if not open_dates:
                    raise ValueError('Enter open dates before importing a supplied-date list or window.')
                base_dates.intersection_update(open_dates)
                using_rule = True
            if except_mode:
                exclusions.update(base_dates)
                exception_has_dates = exception_has_dates or bool(base_dates)
            else:
                result.update(base_dates)
        except ValueError as error:
            raise ValueError(f'Line {number}: {error}') from None
    if needs_exception and not exception_has_dates:
        raise ValueError('All except needs at least one excluded date.')
    if not result and not using_rule:
        raise ValueError('has no dates. Add available dates or an explicit All rule.')
    return sorted(date for date in result - exclusions if date.year not in blocked_years), reader.notes


def parse_import(text, year, start_month, open_dates=None):
    """Return confirmed dates and review notes; one bad block doesn't stop the rest."""
    calendar_date(1, 1, year, start_month)
    result = ImportResult()
    names = {}
    blocks = _split_blocks(text)
    if not blocks:
        raise ValueError('Paste at least one performer and their dates.')
    for name, first_line, lines in blocks:
        if not name:
            result.notes.append(f'Line {first_line}: Start with a performer name, for example Sarah Navy - 11/5.')
            continue
        canonical = names.setdefault(name.casefold(), name)
        try:
            dates, notes = _parse_block(lines, year, start_month, open_dates)
        except ValueError as error:
            result.notes.append(f'{canonical} (line {first_line}) skipped: {error}')
            continue
        if canonical in result.availability:
            result.notes.append(f'{canonical}: repeated entries combined; Script headings do not separate availability.')
        result.availability[canonical] = sorted(set(result.availability.get(canonical, [])) | set(dates))
        result.notes.extend(f'{canonical}: {note}' for note in notes)
    return result


def parse_availability(text, year, start_month, open_dates=None):
    """Compatibility entry point: require all performer blocks to parse successfully."""
    result = parse_import(text, year, start_month, open_dates)
    failures = [note for note in result.notes if ' skipped:' in note or note.startswith('Line ')]
    if failures:
        raise ValueError(failures[0])
    return result.availability
