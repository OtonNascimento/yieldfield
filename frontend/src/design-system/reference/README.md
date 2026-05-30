# Design-system reference (delivered originals)

This directory is the **read-only source of the visual language** (§5A, ARCHITECTURE
`design-system/reference/`). It holds the three delivered files, unchanged:

- `styles.css` — all light/dark tokens + component primitive styles (authoritative palette)
- `charts.jsx` — the three hand-rolled SVG chart primitives (AreaChart, BarChart, Gauge)
- `README.md` — the delivered design-system notes

## Status: awaiting delivery

> ⚠️ **These files are not yet in the repo.** Slice 0 scaffolds the structure; the
> port happens in **Slice 4**. Drop the delivered `styles.css`, `charts.jsx`, and
> `README.md` here before Slice 4 begins. Until then, `tokens/tokens.css` carries
> the authoritative `--brand` value (#605853, §5A) plus clearly-marked **provisional**
> placeholder values that Slice 4 replaces from `styles.css`.

Nothing here is imported or bundled directly — it is the porting source, not shipped
code. The port re-creates the language in typed React under `tokens/`, `theme/`,
`primitives/`, and `charts/`.
