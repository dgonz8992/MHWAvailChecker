"""Venue-aware availability and scheduling, preserving legacy single-venue data."""
from collections import defaultdict
import random
import re

from scheduler import parse_dates, parse_open_dates, infer_date_context
from inline_availability import performer_key, format_inline
from availability_import import ImportResult


def schedule_venues(data):
    return [dict(venue) for venue in data.get('venues', [])] or [
        dict(id='main', name='Main venue', open_dates=data.get('open_dates', ''))]


def combined_dates(venues):
    return sorted({date for venue in venues for date in parse_open_dates(venue['open_dates'])})


def date_text(dates):
    return ', '.join(f'{date.month}/{date.day}/{date.year:04d}' for date in sorted(set(dates)))


def venue_rule(data, name):
    ids = [venue['id'] for venue in schedule_venues(data)]
    rule = data.get('performer_venue_rules', {}).get(performer_key(name))
    if rule is None:
        return dict(mode='shared', venues=ids, availability={}, raw_availability={})
    return dict(rule, venues=[vid for vid in rule.get('venues', ids) if vid in ids])


def _name_pattern(venues):
    return '|'.join(re.escape(v['name']).replace(r'\ ', r'\s+')
                    for v in sorted(venues, key=lambda v: len(v['name']), reverse=True))


def format_venue_availability(name, raw, venues, previous=None):
    """Recognize configured names and explicit 'Venue: availability' sections.

    A named shared rule selects those venues; labeled sections carry separate
    availability. Unknown labels are reviewed rather than silently discarded.
    """
    all_dates = combined_dates(venues)
    if not all_dates:
        raise ValueError('Add open dates to a venue first.')
    pattern = _name_pattern(venues)
    lookup = {performer_key(v['name']): v for v in venues}
    sections = list(re.finditer(r'(?<!\w)(' + pattern + r')(?:\s*(?::|\s[-–—]\s)|'
                               r'(?=\s+(?:(?:all|only|every|available|free|on)\b|\d)))', raw, re.I))
    if len(sections) == 1 and re.search(pattern, raw[:sections[0].start()], re.I):
        sections = []  # "Lobby and Pool: all" is one shared rule.
    for label in re.findall(r'(?m)^\s*([A-Za-z][\w &\-]{0,60})\s*:', raw):
        remainder = re.sub(pattern, '', label, flags=re.I)
        remainder = re.sub(r'\b(?:and|at|for)\b|[\s&,]', '', remainder, flags=re.I)
        if remainder and label.casefold() not in ('dates', 'available', 'availability'):
            raise ValueError(f'Unknown venue {label!r}. Add it to this schedule or use its configured name.')
    if sections:
        if re.search(r'\d|\b(?:all|every|only)\b', raw[:sections[0].start()], re.I):
            raise ValueError('Put availability after each venue name, for example Lobby: only Saturdays.')
        selected, formatted, original, notes = [], {}, {}, []
        for index, section in enumerate(sections):
            venue = lookup[performer_key(section[1])]
            vid = venue['id']
            if vid in selected:
                raise ValueError(f'{venue["name"]} appears twice. Combine its availability into one section.')
            text = raw[section.end():sections[index + 1].start() if index + 1 < len(sections) else len(raw)].strip(' \n;,')
            dates = parse_open_dates(venue['open_dates'])
            if text and dates:
                result = format_inline(name, text, dates)
                if name not in result.availability:
                    raise ValueError(f'{venue["name"]}: ' + ' '.join(result.notes))
                values = result.availability[name]
                notes.extend(result.notes)
            else:
                values = []
            selected.append(vid)
            original[vid], formatted[vid] = text, date_text(values)
        rule = dict(mode='by_venue', venues=selected, availability=formatted, raw_availability=original)
        union = sorted({d for value in formatted.values() for d in parse_open_dates(value)})
        return ImportResult(availability={name: union}, notes=notes), rule
    mentions = list(re.finditer(r'(?<!\w)(' + pattern + r')(?!\w)', raw, re.I))
    selected, excluded = set(), set()
    clean = raw
    for match in reversed(mentions):
        vid = lookup[performer_key(match[1])]['id']
        negative = re.search(r'\b(?:except|excluding|not|no)\s*$', raw[:match.start()], re.I)
        if negative:
            excluded.add(vid)
            clean = clean[:negative.start()] + ' ' + clean[match.end():]
        else:
            selected.add(vid)
            clean = clean[:match.start()] + ' ' + clean[match.end():]
    ids = [v['id'] for v in venues]
    if mentions:
        chosen = [vid for vid in ids if vid in (selected or set(ids)) and vid not in excluded]
        clean = re.sub(r'\b(?:at|venues?|for)\b', ' ', clean, flags=re.I)
        clean = re.sub(r'^\s*(?:and\s+)+|(?:\s+and)+\s*$', ' ', clean, flags=re.I)
    else:
        chosen = (previous or {}).get('venues', ids)
    result = format_inline(name, clean, all_dates)
    if name not in result.availability:
        raise ValueError(' '.join(result.notes))
    return result, dict(mode='shared', venues=chosen, availability={}, raw_availability={})


def generate_venue_schedule(venues, people, rules, minimum_gap=7, *, rng=None):
    if minimum_gap < 0:
        raise ValueError('Minimum days between gigs cannot be negative.')
    by_day = defaultdict(list)
    for venue in venues:
        for day in parse_open_dates(venue['open_dates']):
            by_day[day].append(venue['id'])
    all_dates = sorted(by_day)
    year, month = infer_date_context(all_dates)
    availability = {}
    for name, dates in people.items():
        rule = rules.get(performer_key(name), {})
        selected = rule.get('venues', [v['id'] for v in venues])
        availability[name] = {vid: set(parse_dates(rule.get('availability', {}).get(vid, ''), year, month)
                                      if rule.get('mode') == 'by_venue' else dates) for vid in selected}
    counts, last_booked, rows = dict.fromkeys(people, 0), {}, []
    for day, venue_ids in sorted(by_day.items()):
        candidates = {}
        for vid in venue_ids:
            names = [name for name in people if day in availability[name].get(vid, ())
                     and (name not in last_booked or (day - last_booked[name]).days >= minimum_gap)]
            if rng is not None:
                rng.shuffle(names)
            names.sort(key=lambda name: counts[name])
            candidates[vid] = names
        # Augmenting paths maximize coverage for this date, so a flexible
        # performer cannot accidentally leave a venue-only performer unplaced.
        assigned = {}
        def place(vid, seen):
            for name in candidates[vid]:
                if name in seen:
                    continue
                seen.add(name)
                if name not in assigned or place(assigned[name], seen):
                    assigned[name] = vid
                    return True
            return False
        order = sorted(venue_ids, key=lambda vid: len(candidates[vid]))
        for vid in order:
            place(vid, set())
        booked = {vid: name for name, vid in assigned.items()}
        for vid in venue_ids:
            name = booked.get(vid)
            rows.append((day, vid, name))
            if name is not None:
                counts[name] += 1
                last_booked[name] = day
    return rows, counts


def alternate_venue_schedule(venues, people, rules, gap, previous, *, rng=None):
    rng = rng or random.Random()
    booked = sum(name is not None for _, _, name in previous)
    for _ in range(128):
        rows, counts = generate_venue_schedule(venues, people, rules, gap, rng=rng)
        if rows != previous and sum(counts.values()) >= booked:
            return rows, counts
    return None


def parse_venue_import(source, venues, previous_rules=None):
    from availability_import import _split_blocks
    result = ImportResult()
    result.venue_rules, result.raw_availability = {}, {}
    venue_names = {performer_key(v['name']): v['name'] for v in venues}
    blocks = []
    for name, number, lines in _split_blocks(source):
        key = performer_key(name)
        if key in venue_names and blocks:
            blocks[-1][1].append(venue_names[key] + ': ' + '\n'.join(text for _, text in lines))
        elif name:
            blocks.append((name, [text for _, text in lines]))
    for name, lines in blocks:
        raw = '\n'.join(lines)
        try:
            parsed, rule = format_venue_availability(name, raw, venues, (previous_rules or {}).get(performer_key(name)))
            result.availability[name] = parsed.availability[name]
            result.venue_rules[name] = rule
            result.raw_availability[name] = raw
            labels = [v['name'] for v in venues if v['id'] in rule['venues']]
            result.notes.extend(parsed.notes)
            result.notes.append(f'{name}: {", ".join(labels) or "No venues"} · ' + ('By venue' if rule['mode'] == 'by_venue' else 'Shared dates'))
        except ValueError as error:
            result.notes.append(f'{name} skipped: {error}')
    return result
