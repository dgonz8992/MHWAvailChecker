"""Date parsing and scheduling, independent of the desktop interface."""
from datetime import datetime
import re
import random

from availability_import import calendar_date, extract_dates, parse_availability


def parse_open_dates(text):
    """Require explicit four-digit years for every open date."""
    dates = set()
    for token in text.replace(',', ' ').split():
        try:
            if not re.fullmatch(r'[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}', token):
                raise ValueError('Date must include a four-digit year.')
            month, day, year = map(int, token.split('/'))
            dates.add(datetime(year, month, day))
        except ValueError:
            raise ValueError(f'Invalid open date {token!r}. Use M/D/YYYY, for example 11/3/2026.') from None
    return sorted(dates)


def infer_date_context(open_dates):
    """Use the earliest open date as the reference for yearless availability."""
    if not open_dates:
        raise ValueError('Enter at least one open date in M/D/YYYY format first.')
    first = min(open_dates)
    return first.year, first.month


def parse_dates(text, year, start_month):
    if not 1 <= year <= 9998 or not 1 <= start_month <= 12:
        raise ValueError('Use a year from 1–9998 and a start month from 1–12.')
    dates = set()
    for token in text.replace(',', ' ').split():
        try:
            parts = token.split('/')
            if len(parts) not in (2, 3):
                raise ValueError('Use M/D or M/D/YYYY.')
            month, day = map(int, parts[:2])
            explicit_year = parts[2] if len(parts) == 3 else None
            if explicit_year is not None and (len(explicit_year) not in (2, 4) or not explicit_year.isdigit()):
                raise ValueError('Year must have two or four digits.')
            dates.add(calendar_date(month, day, year, start_month, explicit_year))
        except (ValueError, OverflowError):
            raise ValueError(f'Invalid date {token!r}. Use M/D or M/D/YYYY, for example 11/3/2026.') from None
    return sorted(dates)


def generate_schedule(open_dates, availability, minimum_gap=7, *, rng=None):
    if minimum_gap < 0:
        raise ValueError('Minimum days between gigs cannot be negative.')
    counts = dict.fromkeys(availability, 0)
    last_booked = {}
    rows = []
    for date in sorted(set(open_dates)):
        eligible = [name for name, dates in availability.items()
                    if date in dates and (name not in last_booked or
                                          (date - last_booked[name]).days >= minimum_gap)]
        selected = None
        if eligible:
            fewest = min(counts[name] for name in eligible)
            tied = [name for name in eligible if counts[name] == fewest]
            selected = rng.choice(tied) if rng is not None else tied[0]
        if selected is not None:
            counts[selected] += 1
            last_booked[selected] = date
        rows.append((date, selected))
    return rows, counts


def alternate_schedule(open_dates, availability, minimum_gap, previous_rows, *, rng=None):
    """Try balanced tie choices without reducing the booked-date count.

    None means this bounded search found no alternative, rather than claiming
    the current arrangement is the only valid one.
    """
    rng = rng if rng is not None else random.Random()
    previous_rows = list(previous_rows)
    booked = sum(name is not None for _, name in previous_rows)
    for _ in range(128):
        rows, counts = generate_schedule(open_dates, availability, minimum_gap, rng=rng)
        if rows != previous_rows and sum(counts.values()) >= booked:
            return rows, counts
    return None
