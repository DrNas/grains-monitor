// ENSO (El Niño / La Niña) from NOAA's Climate Prediction Center, no key: the Oceanic Niño Index (3-month running
// Niño-3.4 anomaly) and the alert status and synopsis from the monthly ENSO diagnostic discussion.
import {getText} from '../lib.mjs';

export async function load() {
  const oni = (await getText('https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt', {timeout: 60}))
    .split('\n').map(l => l.trim().split(/\s+/)).filter(c => c.length === 4 && /^\d{4}$/.test(c[1]))
    .map(([seas, yr, total, anom]) => ({seas, yr: +yr, anom: +anom}));
  if (!oni.length) throw new Error('ONI file had no rows');
  let status = null, synopsis = null, issued = null;
  try {
    const t = (await getText('https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml', {timeout: 60}))
      .replace(/<[^>]+>/g, ' ').replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n))
      .replace(/&(nbsp|deg|ntilde|amp|ldquo|rdquo|rsquo|lsquo|ndash|mdash);/g, (_, e) => ({nbsp: ' ', deg: '°', ntilde: 'ñ', amp: '&', ldquo: '“', rdquo: '”', rsquo: '’', lsquo: '‘', ndash: '–', mdash: '—'})[e])
      .replace(/&[a-z]+;/g, ' ').replace(/\s+/g, ' ');
    status = /ENSO Alert System Status:\s*(.*?)\s*Synopsis:/.exec(t)?.[1] || null;
    synopsis = /Synopsis:\s*(.*?)(?:\s\[Fig|\.\s)/.exec(t)?.[1] || null;
    if (synopsis && !synopsis.endsWith('.')) synopsis += '.';
    issued = /issued by\s+CLIMATE PREDICTION CENTER.*?(\d{1,2} [A-Z][a-z]+ \d{4})/i.exec(t)?.[1] || /(\d{1,2} [A-Z][a-z]+ \d{4})/.exec(t)?.[1] || null;
  } catch (e) {}
  const L = oni.at(-1);
  const phase = a => a >= 0.5 ? 'El Niño' : a <= -0.5 ? 'La Niña' : 'Neutral';
  return {data: {oni: oni.slice(-36), latest: {...L, phase: phase(L.anom)}, status, synopsis, issued}, latest: `${L.seas} ${L.yr}`, n: oni.length,
    note: status ? '' : 'could not read the alert status from the CPC discussion', src: 'NOAA CPC Oceanic Niño Index and ENSO diagnostic discussion'};
}
