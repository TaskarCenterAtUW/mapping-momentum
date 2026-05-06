---
agent: ask
model: gpt-4.1
description: Convert a loosely formatted date/time/timezone into ISO 8601 UTC JSON for event configs.
---

<!-- @format -->

Convert a loosely formatted date, time, and timezone into ISO 8601 UTC format for use in event config JSON. Output ONLY the JSON code block — no explanations, no prose, no labels.

# Input Format

Input begins with `/time` followed by one or two datetime expressions. A range is indicated by a `-` separator between two times. A single datetime produces a single `"time"` field; a range produces a `"time_window"` with `"start"` and `"end"`.

Dates and times may be written in any reasonable format, e.g.:

- `2026-01-20 11:00 AM PT`
- `Jan 1, 2026, 12:00 PM ET`
- `1/3 3:30 AM PT` (year inferred from context or current year)
- `March 15 2026 9pm CT`

# Steps

Before producing output, reason through the following steps internally (do not output this reasoning):

1. **Parse date**: Identify year, month, and day from the input. If the year is omitted, assume the current year.
2. **Parse time**: Identify hours and minutes (and seconds if given). If seconds are absent, use `00`. Normalize 12-hour AM/PM to 24-hour.
3. **Identify timezone**: Map the timezone abbreviation to a UTC offset using DST rules below.
4. **Convert to UTC**: Subtract the UTC offset from the local time, rolling over date/hour as needed.
5. **Format**: Produce `YYYY-MM-DDTHH:MM:SSZ` (always UTC, always `Z` suffix, zero-padded).
6. **Detect range vs. single**: If two times are present, produce `time_window`; if one, produce `time`.

# Timezone Reference

Use these UTC offsets. Apply DST (daylight saving) when the date falls between the second Sunday in March and the first Sunday in November (US rules).

| Abbreviation      | Standard (no DST) | Daylight (DST)  |
| ----------------- | ----------------- | --------------- |
| PT / PST / PDT    | UTC−8             | UTC−7           |
| MT / MST / MDT    | UTC−7             | UTC−6           |
| CT / CST / CDT    | UTC−6             | UTC−5           |
| ET / EST / EDT    | UTC−5             | UTC−4           |
| AKT / AKST / AKDT | UTC−9             | UTC−8           |
| HT / HST          | UTC−10            | UTC−10 (no DST) |
| UTC / Z / GMT     | UTC±0             | UTC±0           |

If the input uses an explicit offset (e.g., `UTC-7`, `+05:30`), use that offset directly.

# Output Format

Output ONLY a single fenced JSON code block. No text before or after it.

**Range (two times):**

```json
"time_window": {
  "start": "YYYY-MM-DDTHH:MM:SSZ",
  "end": "YYYY-MM-DDTHH:MM:SSZ"
}
```

**Single time:**

```json
"time": "YYYY-MM-DDTHH:MM:SSZ"f
```

# Examples

**Input:** `/time 2026-01-20 11:00 AM PT - 5:00 PM PT`

Jan 20, 2026 is in standard time (before second Sunday in March). PT = UTC−8.
11:00 AM PT → 19:00:00 UTC → `2026-01-20T19:00:00Z`
5:00 PM PT → 01:00:00 UTC next day → `2026-01-21T01:00:00Z`

**Output:**

```json
"time_window": {
  "start": "2026-01-20T19:00:00Z",
  "end": "2026-01-21T01:00:00Z"
}
```

---

**Input:** `/time Jan 1, 2026, 12:00 PM PT - 1/3 3:30 AM PT`

Jan 1 and Jan 3, 2026 are both in standard time. PT = UTC−8.
12:00 PM PT Jan 1 → 20:00:00 UTC → `2026-01-01T20:00:00Z`
3:30 AM PT Jan 3 → 11:30:00 UTC → `2026-01-03T11:30:00Z`

**Output:**

```json
"time_window": {
  "start": "2026-01-01T20:00:00Z",
  "end": "2026-01-03T11:30:00Z"
}
```

---

**Input:** `/time March 15 2026 9pm PT`

Mar 15, 2026 is after the second Sunday of March (Mar 8) → DST active. PT = UTC−7.
9:00 PM PT → 04:00:00 UTC next day → `2026-03-16T04:00:00Z`

**Output:**

```json
"time": "2026-03-16T04:00:00Z"
```

# Notes

- Always use `Z` (UTC) suffix — never emit a local offset in the output.
- If a timezone is ambiguous or unrecognized, default to UTC and note nothing (still output only the code block).
- The `-` in a range is a separator between two datetimes. Do not confuse it with a date separator inside a single expression (e.g., `2026-01-20`).
- If the end time has no date, assume it shares the same date as the start. After converting **any** time to UTC, if the result exceeds 23:59:59, roll the date forward by one day. This applies regardless of whether the date was explicit or inferred.
