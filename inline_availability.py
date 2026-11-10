"""Snapshots and local import formatting for inline performer availability."""
import hashlib
import json
import uuid


def performer_key(name):
    return ' '.join(name.split()).casefold()


def validate_performer_names(people):
    seen = set()
    for person in people:
        key = performer_key(person['name'])
        if key and key in seen:
            raise ValueError(f"The performer name {person['name'].strip()!r} is already used. Enter a unique name.")
        seen.add(key)


def request_signature(draft, data):
    value = ['local-import-v2', draft['name'].strip(), draft['availability'].strip(), data.get('open_dates', '')]
    if data.get('venues'):
        value.extend([data['venues'], data.get('performer_venue_rules', {}).get(performer_key(draft['name']))])
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def performer_value(data, name):
    return next((person['availability'] for person in data.get('performers', [])
                 if performer_key(person['name']) == performer_key(name)), None)


def schedule_performers(data):
    """Recover names saved by either screen, including unformatted drafts."""
    people = [dict(person) for person in data.get('performers', [])]
    names = {performer_key(person['name']) for person in people}
    for draft in data.get('availability_drafts', []):
        name = draft['name'].strip()
        if name and performer_key(name) not in names:
            people.append(dict(name=name, availability=draft.get('formatted', '')))
            names.add(performer_key(name))
    return people


def editor_drafts(data):
    """Preserve original draft text while recovering missing saved performers."""
    existing = {performer_key(draft['name']): draft for draft in data.get('availability_drafts', [])
                if draft['name'].strip()}
    drafts = []
    for person in schedule_performers(data):
        draft = existing.get(performer_key(person['name']))
        if draft is None:
            draft = dict(id=str(uuid.uuid4()), availability=person['availability'],
                         status='Existing performer', formatted=person['availability'])
        drafts.append(dict(draft, name=person['name']))
    drafts.extend(dict(draft) for draft in data.get('availability_drafts', []) if not draft['name'].strip())
    return drafts


def sync_inline_performers(data, drafts):
    """Apply the inline roster, using draft IDs to follow renames and removals."""
    validate_performer_names(drafts)
    previous = {draft['id']: draft for draft in data.get('availability_drafts', [])}
    existing = {performer_key(person['name']): person for person in data.get('performers', [])}
    people, names = [], set()
    for draft in drafts:
        name = draft['name'].strip()
        key = performer_key(name)
        if not name or key in names:
            continue
        old_name = previous.get(draft['id'], {}).get('name', name)
        rules = data.get('performer_venue_rules', {})
        if performer_key(old_name) != key and performer_key(old_name) in rules:
            rules[key] = rules.pop(performer_key(old_name))
        person = existing.get(performer_key(old_name)) or existing.get(key)
        value = person['availability'] if person else ''
        if not draft['availability'].strip():
            value = ''
        people.append(dict(name=name, availability=value))
        names.add(key)
    if people != data.get('performers', []):
        data['rows'] = []
    data['performers'] = people
    data['availability_drafts'] = drafts
    if 'performer_venue_rules' in data:
        data['performer_venue_rules'] = {key: rule for key, rule in data['performer_venue_rules'].items() if key in names}


def sync_schedule_performers(data, people):
    """Apply full-editor changes without replacing unchanged original draft text."""
    validate_performer_names(people)
    previous = {performer_key(person['name']): person for person in data.get('performers', [])}
    drafts = {performer_key(draft['name']): draft for draft in editor_drafts(data) if draft['name'].strip()}
    updated = []
    for person in people:
        key = performer_key(person['name'])
        draft = dict(drafts.get(key) or dict(id=str(uuid.uuid4()), name=person['name'],
                                           availability=person['availability'], status='Existing performer'))
        old = previous.get(key)
        if (old is not None and old['availability'] != person['availability']) or (old is None and person['availability']):
            for field in ('last_applied', 'formatted', 'review_notes'):
                draft.pop(field, None)
            draft.update(availability=person['availability'], status='Updated from schedule')
        draft['name'] = person['name']
        updated.append(draft)
    updated.extend(dict(draft) for draft in data.get('availability_drafts', []) if not draft['name'].strip())
    data['performers'] = [dict(person) for person in people]
    data['availability_drafts'] = updated
    if 'performer_venue_rules' in data:
        keys = {performer_key(person['name']) for person in people}
        data['performer_venue_rules'] = {key: rule for key, rule in data['performer_venue_rules'].items() if key in keys}


def format_inline(name, availability, dates):
    """Use Import's parser while keeping the row's name separate from pasted text."""
    from availability_import import ImportResult, parse_import
    from scheduler import infer_date_context
    year, month = infer_date_context(dates)
    label = 'Inline performer'
    result = parse_import(f'{label} - {availability}', year, month, dates)
    notes = [note.replace(label, name) for note in result.notes]
    if set(result.availability) != {label}:
        return ImportResult(notes=notes + ['Enter availability for this performer only.'])
    confirmed = [date for date in result.availability[label] if date in dates]
    if len(confirmed) != len(result.availability[label]):
        notes.append('Dates outside the schedule’s open dates were excluded.')
    return ImportResult(availability={name: confirmed}, notes=notes)
