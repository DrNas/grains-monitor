# Video recaps

One file per day, `YYYY-MM-DD.json` (the video's publish date), written by the scheduled "Grain Markets daily video summary" task and shown in the Daily recap section. Summaries only: never the transcript or long quotes. The newest 10 files are published.

```json
{
  "date": "2026-11-04",
  "channel": "Grain Markets and Other Stuff",
  "title": "Video title as on YouTube",
  "url": "https://www.youtube.com/watch?v=...",
  "published": "2026-11-04",
  "sections": [
    {"topic": "Exports / demand", "bullets": ["...", "..."]},
    {"topic": "Price action & funds", "bullets": ["..."]}
  ],
  "flags": ["optional: auto-caption errors or anything uncertain"]
}
```
