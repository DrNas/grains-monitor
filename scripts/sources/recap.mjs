// Video recaps committed to data/recaps/YYYY-MM-DD.json by the scheduled summary task (schema in
// data/recaps/README.md). Reads the repository, no network. Malformed files are skipped and named in the note.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../data/recaps');
const KEEP = 10;
const str = (v, max) => typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null;

export async function load() {
  const files = fs.existsSync(DIR) ? fs.readdirSync(DIR).filter(f => /^\d{4}-\d\d-\d\d\.json$/.test(f)).sort().reverse() : [];
  const recaps = [], bad = [];
  for (const f of files) {
    if (recaps.length >= KEEP) break;
    try {
      const j = JSON.parse(fs.readFileSync(path.join(DIR, f), 'utf8'));
      const url = str(j.url, 300);
      if (!url || !/^https:\/\/(www\.)?(youtube\.com|youtu\.be)\//.test(url)) throw new Error('url missing or not YouTube');
      const sections = (Array.isArray(j.sections) ? j.sections : []).map(s => ({topic: str(s?.topic, 80) || 'Notes',
        bullets: (Array.isArray(s?.bullets) ? s.bullets : []).map(b => str(b, 600)).filter(Boolean).slice(0, 15)})).filter(s => s.bullets.length).slice(0, 12);
      if (!sections.length) throw new Error('no bullets');
      recaps.push({date: f.slice(0, 10), channel: str(j.channel, 80) || 'YouTube', title: str(j.title, 200) || '(untitled)', url,
        published: str(j.published, 20), sections, flags: (Array.isArray(j.flags) ? j.flags : []).map(x => str(x, 300)).filter(Boolean).slice(0, 8)});
    } catch (e) { bad.push(`${f} (${e.message.slice(0, 60)})`); }
  }
  return {data: {recaps}, latest: recaps[0]?.date || null, n: recaps.length,
    note: (recaps.length ? '' : 'no recaps yet') + (bad.length ? `${recaps.length ? '' : '; '}skipped: ${bad.join(', ')}` : ''),
    partial: bad.length > 0, src: 'Daily video summary task (data/recaps/)'};
}
