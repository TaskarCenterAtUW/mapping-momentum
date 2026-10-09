# Offline examples

This directory contains two complete, synthetic Workspace runs. They make no
network requests and use no real names, photographs, or credentials.

Run these commands from the repository root after installing the project
dependencies:

```bash
python example/run_offline.py \
  --config example/minimal \
  --output-dir /tmp/mapping-momentum-minimal-output

python example/run_offline.py \
  --config example/maximal \
  --output-dir /tmp/mapping-momentum-maximal-output
```

Each command validates `event.json`, loads the local quest definition, parses
the synthetic map/changeset/note payloads, enriches elements, computes metrics,
and writes both `stats.json` and `index.html`.

## Minimal

`minimal/` contains only the fields and payloads needed for one valid report:
one synthetic mapped element, one changeset, an empty notes response, and a
small quest definition.

## Maximal

`maximal/` exercises every supported report-content feature:

- local `showcase_photos`;
- local `pictures` directory embedding;
- quotes with every optional attribution field;
- a slideshow URL list;
- a direct video-file URL;
- multiple mapped elements, a way geometry, field-photo URLs, and notes.

The slideshow and video URLs use reserved `example.invalid` domains. They are
only rendered into the offline HTML; the runner never fetches them.
