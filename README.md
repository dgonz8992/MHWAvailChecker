# MHW Scheduler

A desktop application for scheduling performers on open dates. Enter open dates
and add or import performer availability to get started.

## Run

In PyCharm, run `main.py` using the project's `.venv-modern` interpreter.

On this Mac, you can also double-click **Launch MHW.command** in Finder, or run:

```sh
.venv-modern/bin/python main.py
```

Requires Python 3.9 or newer with Tkinter. There are no third-party dependencies.
On modern macOS, use a Python installation from python.org with its bundled
modern Tcl/Tk. Apple's Command Line Tools Python uses old Tk 8.5.9, which can
open blank windows even though the scheduling code and widget creation work.

If the window is blank, install Python from https://www.python.org/downloads/macos/.
In PyCharm's Python Interpreter settings, add a new virtual environment using
the newly installed Python as its base interpreter. Use `.venv-modern` as the
environment directory and select it for this project. Run `main.py` again.
The Finder launcher also prefers `.venv-modern` when it exists.

## Standalone Mac app

Open `dist/MHW Scheduler.app` to run without Python or PyCharm.
You can drag the app into Applications. To share it, send
`dist/MHW Scheduler.zip`; the recipient should unzip it before opening
the app. The build contains both Apple Silicon and Intel executables.

This local build is not signed with an Apple Developer ID or notarized. macOS may
require approval in System Settings → Privacy & Security when opening a shared copy.

After changing the source code, run `Build Mac App.command` to rebuild the app and
the sharing ZIP. Building requires `.venv-modern` and internet access to install
the pinned PyInstaller build dependency. Recipients do not need either.

## Appearance

Click the **sun / Appearance** button at the bottom to open its dropdown.
Choose **Default**, **Dark**, **Miami Vice**, **Rose Quartz**, or **Crimson Noir** to switch instantly.
The choice applies to the schedule list, folders, notes, schedule editor, and
app dialogs, and is remembered on this Mac. Default uses a white background
with blue primary buttons and green Generate / Save actions. Saved Light
preferences from older builds are recognized as Default.
Miami Vice uses a navy background with cyan highlights and pink actions.
Rose Quartz pairs soft blush surfaces with deep rose buttons and warm plum text.
Crimson Noir pairs near-black surfaces with crimson buttons and bright red accents.
Switching appearance preserves your current selection and unsaved input.

## Use

The app opens to **Schedules**. Choose **New schedule…** and name the schedule,
or double-click an existing schedule to open it. Right-click any schedule for
**Open**, **Rename…**, **Move to folder…**, and **Delete…**. Mac Control-click
and trackpad secondary-click also work. Delete asks for confirmation. Use
**All schedules** inside an open schedule to return to the list. The list uses compact,
uniform rows with a horizontal divider under each schedule.

Use the **Folders** sidebar to switch between **All schedules** and folders you
create. Schedules without a folder are available under All schedules. **New folder…** creates an empty folder;
**Rename folder…** changes its name without moving its schedules. You can also
right-click a folder for **Open**, **Rename…**, and **Delete folder…**. Deleting a
folder asks for confirmation and keeps its schedules in **All schedules**,
preserving bookings and notes. The built-in All schedules view cannot be deleted. Select one or
more schedules using their checkboxes, right-click a checked schedule, and
choose **Move to folder…** to file them
or choose **No folder** to remove their folder assignment. New schedules are created inside the selected folder.
**Search** searches schedule names, performer names (including drafts), notes,
and folder names within the current folder. Partial performer names also match.
While searching, expanded performer tables show only names matching the search.
Clear Search to show everyone again; filtering does not remove saved performers.
Drag folders up or down in the sidebar to reorder them. The order saves on drop
and returns after restarting. All schedules stays pinned at the top. Renaming
keeps a folder in its position, and new folders are appended at the bottom.

Click anywhere in a schedule’s **Notes** cell to edit directly in its row. Notes save
automatically; click outside the field or press Command/Control+Enter to finish.
The same notes can be edited inside
an open schedule; both screens stay in sync and keep generated bookings intact.

Each schedule saves its open dates, performer availability, minimum gap,
AI model selection, and generated schedule automatically. Confirmation scripts,
names, and totals are restored from the saved schedule. Unfinished input is
saved too. **Save now** saves immediately; navigating away or closing the window
also saves. API keys stay in memory and are never stored in schedules.

Schedules are local to this Mac in
`~/Library/Application Support/MHW Scheduler/campaigns.sqlite3`, separate from
the app so rebuilding or replacing the app preserves them. Sharing the app ZIP
does not share saved schedules.

1. Enter open dates in **M/D/YYYY** format, for example `11/3/2026`, separated by
   commas, spaces, or new lines. Each date must include a four-digit year.
2. Edit performer availability or use the importer; add or remove performers as needed.
3. Set the minimum days between bookings and click **Generate schedule** to see
   bookings, unfilled dates, and gig totals.

The app derives the year for yearless availability from the earliest open date.
For example, with open dates starting in November 2026, `12/8` means December 8,
2026 and `1/4` means January 4, 2027. Explicit years in availability are preserved.
For dates that span more than one annual cycle, include explicit years in
availability to distinguish repeated months.

Dates are sorted chronologically and duplicates count once. Availability dates
that aren't open dates do not receive bookings.

### Performer tables in the schedule list

Click the disclosure arrow beside a schedule to expand its **Performer availability**
table. Right-click a schedule and choose **Expand all** or **Collapse all** to
open or close every schedule currently shown in the folder/search results.
Paste a newline-separated name list into a Name cell, or use **Paste names**.
The table creates one row per name and reuses matching names rather than adding
case-insensitive duplicates. Draft names and raw availability are saved per schedule.
Both screens share the same performer roster: adding, renaming, or removing a
performer in the expanded list updates the full schedule, and full-schedule edits
and imports update the expanded list. Names appear even before availability is
filled in. Unchanged original availability text is preserved; confirmed date edits
in the full schedule appear in the expanded table when you return.

Enter each performer’s availability in their row. Leaving a completed cell (or
pressing Command/Control+Enter in Availability) runs the same local formatter used by Import automatically. No API key is needed.
Confirmed dates update the matching performer inside the schedule; new names are
added. Existing bookings clear when availability changes so you can generate a fresh
schedule. Ambiguous inputs and errors remain as drafts with a status and **Retry**.

Add or edit **Open dates** in the tall left-hand column beside the compact performer table using
M/D/YYYY, separated by commas or new lines. Dates save automatically and also
appear in the full schedule. Leaving the dates field formats completed performer
rows using the updated dates. Availability cells expand for multiline input.
Formatting happens on your Mac using the import parser. Dates outside the
schedule’s open dates are excluded. Raw text and any review notes stay saved.
AI remains an optional feature in the separate Import dialog.

### Import pasted availability

You can also paste availability directly into a performer’s field inside the
full schedule. Clicking outside the field (or Command/Control+Enter) converts it
with the same local formatter, saves the confirmed dates, and keeps the expanded
list in sync. Unclear text stays in the field with a review message so you can
correct it; no API key is required.

Click **Import availability…**, paste the original list (or load a UTF-8 `.txt`
file), and click **Preview import**. The preview shows converted dates and review
notes. **Import converted dates** applies them; **Back to text** lets you correct
entries first. Previewing does not change the current project.

The importer supports the formats from the example list:

| Input | Interpretation |
| --- | --- |
| `11/26`, `11/ 26`, `11-26`, `12.27`, `12:4` | Numeric month/day dates |
| `11/26/2026`, `1/2/27`, `2027-01-02` | Explicit years are preserved; two digits mean 2000–2099 |
| `November 20, 27, 28` | All three dates use November |
| `Dec 11`, `December 10 and 17th` | Full or abbreviated month names and ordinal days |
| `12/11 & 12`, `12/17 & 18` | Additional days share the preceding month |
| `January` followed by `2nd`, `5th`, etc. | Month headings carry across lines |
| `12/20-12/24`, `12/30-1/2` | Inclusive ranges, including year rollover |
| `All`, `all of these`, `available for every date` | Current open dates |
| `All except 10/31`, `any date except 10/24` | Current open dates minus exclusions |
| `all December and January`, `all the January dates` | Open dates in those months |
| `Sundays and Tuesday’s except ...` | Open dates on those weekdays, minus exceptions |
| `Every weekend, monday and thursday` | Open dates on the specified weekdays; explicit additional dates are included |
| `the 3rd of January`, `Christmas`, `New Year's Day` | January 3, December 25, January 1 |
| A list with `✅` selections | Only checked date lines are included |
| `January 2027: 3, 7, 19`, `Jan '28: 13, 21` | Month/year headings apply to the following days |
| `03 Aug 2027`, `March 4th, 12th & 20th (2027)` | Day-first written dates and trailing years |
| `For 2028, I'm free Jan 5 ...`, `... all 2027` | A written year qualifies that performer's yearless dates |
| `All supplied dates in January and February 2027` | Open dates limited to those months and that year |
| `June 4–June 20, 2027, any supplied date in that window` | Only open dates inside the inclusive window |
| Explicit dates followed by `all good` | Keeps the explicit list; does not add every open date |
| `No availability in 2028` | Removes dates in that year from the performer's result |

Dates are interpreted as US month/day dates. Set open dates first; the earliest
open date supplies the reference year and month for yearless dates. Imported
dates display their full years.

Lines containing **Script** (ignoring letter case) are discarded and end the
previous performer block. Names without dates are skipped and listed in review
notes; they never imply availability. Blank lines, rates such as `$700`, chat
timestamps such as `11:12 am`, and known labels such as `Bin 47`/`Shed` are ignored.
The importer combines confirmed dates from those labels into one performer list.
Repeated performer names are combined across sections and reported in the
preview; this app does not keep separate venue schedules.

Tentative dates such as `(maybe14)` are omitted with a review note. A chain such
as `12/5-12/20-12/21` is interpreted as a list of dates and flagged for review;
a pair such as `12/20-12/24` is interpreted as a range. Familiar input typos such
as `Febuary`, `22st`, and `2/one` are handled.

Ambiguous or invalid performer blocks are skipped with an explanation while
other performers remain available to import. For example, `4/5th and 31st`
would imply April 31, and `new years` does not specify Day or Eve. Correct those
entries in the pasted text and preview again. The parser follows these rules;
it cannot reliably infer every possible natural-language message.

The additional 50-example fixture covers quoted messages, bracketed/JSON-style
lists, arrows and other separators, multiple month/year headings, year-scoped
supplied-date rules, and positive lists followed by "other dates don't work."
Written year qualifiers stay within one performer block; they do not affect
other performers. Supplied-date counts such as "all three" produce a review
note if the number of matching open dates differs.

By default, importing adds new performers and replaces availability for matching
names (ignoring letter case), keeping other performers and open dates. Select
**Replace all performers** to keep only the converted performers. Select
**Also replace open dates** to use the combined converted dates as open dates.
Skipped performers are not added or updated; replacing all performers removes
any existing performers not in the converted result.

All/month/weekday rules resolve against the current open dates at preview time.
If you change the open dates later, import those rules again. No third-party
packages are required for the local parser.

### Optional AI conversion

In **Import availability…**, enable **Use AI conversion (OpenAI API)** to have an
AI model read the pasted text. Enter an OpenAI API key in the masked **API key**
field, or supply `OPENAI_API_KEY` in the process environment (for example, in
PyCharm's run configuration). Keys entered into the app stay in memory and are
not saved to a file. Do not put an API key in source code or commit it to GitHub.

The default model is `gpt-5-mini`; change the **Model** field or set `OPENAI_MODEL`
to use another model with Responses API and Structured Outputs support. This
uses the OpenAI API over HTTPS; no additional Python packages are needed.

1. Enter all open dates in M/D/YYYY format in the main window.
2. Paste availability, enable AI conversion, and click **Preview import**.
3. Wait for the conversion, review its dates and notes, then click
   **Import converted dates** to apply the result.

AI conversion sends the pasted text and current open dates to OpenAI and incurs
API usage charges. No key or network connection is needed with AI conversion
unchecked. The app does not make API calls when starting or while typing.

The AI returns availability only for the current open dates, so **Also replace
open dates** is disabled in AI mode. The response uses a strict structured schema
and is validated locally: selected dates must come from the supplied list, names
must appear in their source excerpts, and uncertain performers are skipped and
shown in review notes. Previewing does not change the schedule or inputs.
AI interpretation can still be wrong; review the dates before importing.

Conversion runs in a background thread so the window stays responsive. Closing
the import window discards its eventual result; an already submitted API request
can still finish and incur usage. Network, authentication, model access, rate
limit, and incomplete-response errors are shown without applying partial results.
Requests set `store: false`; this is not a claim of zero data retention.

Implementation references: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
and [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini).

The scheduler chooses an available performer with the fewest gigs so far,
requiring at least the configured number of days since their previous booking.
Ties follow the displayed performer order. It makes one booking at a time and
does not revisit earlier bookings, so it does not guarantee the best possible
schedule. Unfilled dates can reflect either availability or the spacing rule.

After generating, click **Try another arrangement** to try different assignments.
It varies ties between eligible performers with the fewest gigs, keeps the same
availability and minimum spacing, and only replaces the current arrangement if
it finds a different one with at least as many booked dates. You can click again
for more variations. If none is found, your current schedule stays in place.
The chosen arrangement saves automatically, including updated names, totals,
and confirmation scripts. This is a bounded search, not an exhaustive optimizer.

Input edits clear previous results; generate again to see current results.
Inputs and results remain in memory for the current session.
The launcher opens a desktop window; it is not a bundled standalone `.app`.

### Copying

- **Copy dates** copies the open-date input. **Copy availability** copies performer
  names and their date lists in the `Name - dates` import format.
- **Copy schedule** copies all generated rows with tab-separated Date, Day, and
  Performer columns for pasting into a spreadsheet. **Copy selected** copies only
  selected rows, in displayed order. **Copy totals** copies the gig counts.
- Below the schedule, **Performer names in schedule order** contains one row per
  scheduled date, with repeated names preserved. **Copy names** copies one name
  per line with no header or extra columns, ready to paste into a table column.
  Blank rows preserve alignment for unfilled dates. **Copy selected names**,
  keyboard copying, and right-click copying also work in this table.
- In the import preview, **Copy preview** copies all converted dates and review notes.
- Right-click text fields, performer names, labels, status text, or schedule rows
  for a copy menu. Editable fields also offer Cut and Paste.
- Use **Cmd+A / Cmd+C** on Mac or **Ctrl+A / Ctrl+C** on Windows/Linux to select
  and copy text or schedule rows. The read-only preview supports selection and copying.

### Scrolling

Use the mouse wheel or trackpad over date fields, performer availability,
schedule tables, or import previews to scroll them. When a field reaches its
edge, scrolling continues in its containing performer list or page. The main
page and the complete import/preview dialogs have vertical and horizontal
scrollbars so all controls remain reachable in smaller windows. Scrolling over
labels, buttons, blank space, or scrollbars also scrolls the containing page.
Tk 9's separate precise trackpad events are supported, including horizontal
gestures; Shift-wheel scrolls horizontally. Date fields and performer date lists
also have their own scrollbars.

## Check scheduling rules

```sh
.venv/bin/python -m unittest -v
```
