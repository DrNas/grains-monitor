// Weather regions: a few representative points per growing or feeding area. Each region's numbers are the plain
// average of its points. Normals for these exact points are in data/weather-normals.json (scripts/build-normals.mjs):
// if you add or move a point, rebuild the normals.
// season: months (1-12) when the region matters most for prices; it is highlighted then and dimmed otherwise.
export const REGIONS = [
  {id: 'cb_w', name: 'Western Corn Belt', crops: 'corn, soybeans', season: [4, 5, 6, 7, 8, 9], points: [
    ['Des Moines, IA', 41.59, -93.62], ['Lincoln, NE', 40.81, -96.70], ['Mankato, MN', 44.16, -94.00]]},
  {id: 'cb_e', name: 'Eastern Corn Belt', crops: 'corn, soybeans, SRW wheat', season: [4, 5, 6, 7, 8, 9], points: [
    ['Champaign, IL', 40.12, -88.24], ['Indianapolis, IN', 39.77, -86.16], ['Columbus, OH', 39.96, -83.00]]},
  {id: 'hrw', name: 'Southern Plains (HRW wheat)', crops: 'KC wheat', season: [9, 10, 11, 3, 4, 5, 6], points: [
    ['Salina, KS', 38.84, -97.61], ['Dodge City, KS', 37.75, -100.02], ['Enid, OK', 36.40, -97.88]]},
  {id: 'npl', name: 'Northern Plains', crops: 'spring wheat, corn, soybeans', season: [4, 5, 6, 7, 8], points: [
    ['Fargo, ND', 46.88, -96.79], ['Minot, ND', 48.23, -101.30]]},
  {id: 'delta', name: 'Mid-South / Delta', crops: 'soybeans, corn, rice, SRW wheat', season: [4, 5, 6, 7, 8], points: [
    ['Stuttgart, AR', 34.50, -91.55]]},
  {id: 'br_cw', name: 'Brazil Center-West', crops: 'soybeans, safrinha corn', season: [10, 11, 12, 1, 2, 3, 4, 5], points: [
    ['Sorriso, MT', -12.55, -55.71], ['Rio Verde, GO', -17.80, -50.93]]},
  {id: 'br_s', name: 'Southern Brazil', crops: 'soybeans, corn', season: [10, 11, 12, 1, 2, 3], points: [
    ['Cascavel, PR', -24.96, -53.46], ['Passo Fundo, RS', -28.26, -52.41]]},
  {id: 'ar', name: 'Argentina core', crops: 'soybeans, corn, wheat', season: [11, 12, 1, 2, 3], points: [
    ['Pergamino, BA', -33.89, -60.57], ['Marcos Juárez, CBA', -32.70, -62.10]]},
  {id: 'feed', name: 'Feedlot belt', crops: 'fed cattle (heat and cold stress)', season: [1, 2, 3, 6, 7, 8, 12], livestock: true, points: [
    ['Garden City, KS', 37.97, -100.87], ['Hereford, TX', 34.82, -102.40], ['Grand Island, NE', 40.93, -98.34]]},
];
export const ALL_POINTS = REGIONS.flatMap(r => r.points.map(([name, lat, lon]) => ({region: r.id, name, lat, lon})));
