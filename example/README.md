<!-- @format -->

# Offline examples

This directory contains two complete, synthetic Workspace runs. They make no network requests and use no real names, photographs, or credentials.

Run these commands from the repository root after installing the project dependencies:

```bash
python example/run_offline.py \
  --config example/minimal \
  --output-dir /tmp/mapping-momentum-minimal-output

python example/run_offline.py \
  --config example/maximal \
  --output-dir /tmp/mapping-momentum-maximal-output
```

Each command validates `event.json`, loads the local quest definition, parses the synthetic map/changeset/note payloads, enriches elements, computes metrics, and writes both `stats.json` and `index.html`.

## Generated outputs

Generated outputs are checked in so they can be reviewed without running the examples:

- [Minimal stats](minimal/output/events/example-minimal/walkabout/stats.json)
  · [Minimal report](minimal/output/events/example-minimal/walkabout/index.html)
- [Minimal anonymized stats](minimal/output-anonymized/events/example-minimal/walkabout/stats.json)
  · [Minimal anonymized report](minimal/output-anonymized/events/example-minimal/walkabout/index.html)
- [Maximal stats](maximal/output/events/example-maximal/walkabout/stats.json)
  · [Maximal report](maximal/output/events/example-maximal/walkabout/index.html)
- [Maximal anonymized stats](maximal/output-anonymized/events/example-maximal/walkabout/stats.json)
  · [Maximal anonymized report](maximal/output-anonymized/events/example-maximal/walkabout/index.html)

Regenerate the committed artifacts with:

```bash
python example/run_offline.py \
  --config example/minimal \
  --output-dir example/minimal/output

python example/run_offline.py \
  --config example/maximal \
  --output-dir example/maximal/output

python example/run_offline.py \
  --config example/minimal \
  --output-dir example/minimal/output-anonymized \
  --anonymize

python example/run_offline.py \
  --config example/maximal \
  --output-dir example/maximal/output-anonymized \
  --anonymize
```

The anonymized variants retain the report metrics and content while replacing known participant names with `Participant N` labels in the contributor list, map histories, quote attributions, and matching note/quote text.

## Minimal

`minimal/` contains only the fields and payloads needed for one valid report: one synthetic mapped element, one changeset, an empty notes response, and a small quest definition.

## Maximal

`maximal/` exercises every supported report-content feature:

- local `showcase_photos`;
- local `pictures` directory embedding;
- quotes with every optional attribution field;
- a slideshow URL list;
- a direct video-file URL;
- multiple mapped elements, a way geometry, field-photo URLs, and notes.

The slideshow and video URLs use reserved `example.invalid` domains. They are only rendered into the offline HTML; the runner never fetches them.
