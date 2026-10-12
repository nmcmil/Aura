# Architecture

Aura has one native GTK interface and a renderer that can run without a toolkit.

| File | Responsibility |
| --- | --- |
| `aura/model.py` | Versioned recipes, effects, palettes, validation, monitor geometry |
| `aura/render.py` | Deterministic pixels, strip rendering, PNG encoding, atomic export |
| `aura/store.py` | SQLite designs and immutable export-history snapshots |
| `aura/app.py` | Native wallpaper workspace, action center, preview scheduling and export workflow |
| `aura/studio.py` | Presentation labels, adjustment units and contextual visibility |
| `aura/__main__.py` | Native launch or headless recipe export |

The UI has one preview worker, one thumbnail worker and one export worker. Preview requests are coalesced while completed frames remain visible. Thumbnail work runs one job at a time and discards stale panel requests. Exports capture a recipe snapshot so later edits do not change a running job. Workers belong to the application process; there is no resident service.

AppWindow, CreativeWorkspace, FloatingPanel and ActionCenter own the native chrome. Style, Colors and Adjust occupy the native left floating panel, folded into a header/bottom drawer on compact windows. The output action bar contains Size, More and Export; these panels temporarily replace creation controls on compact windows. The native bar shows the clickable resolution, More and Export; More opens the toolkit menu. Saved designs, history and export progress use grown output surfaces. Creation controls use the native left floating panel; output controls use the bottom action center.

PNG exports evaluate each strip at output resolution. Coordinate-based grain makes strips and monitor crops agree exactly. The encoder writes to a temporary file beside the destination, flushes it, and replaces the destination after completion. Cancellation removes the incomplete temporary file. Batch export retains completed images and records each in history.

Recipes remain at schema version 1 after the rename. New files use Aura names, including the `Aura recipe` PNG metadata key. JSON imports do not depend on a filename extension. Existing Wally libraries are reused when there is no Aura directory; the app does not copy, delete, or merge user libraries.

The native app ID is `io.github.nmcmil.Aura`, the command and Python module are `aura`, and the Python distribution is `aura-wallpaper`.
