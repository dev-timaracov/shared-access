export const outcomes = {progress:'В работе',implemented:'Реализовано',blocked:'Блокировка',handoff:'Передача'};
export function groupReports(reports) {
  const days = new Map();
  for (const report of reports) {
    const day = report.created_at.slice(0,10);
    if (!days.has(day)) days.set(day,{day,total:0,progress:0,implemented:0,blocked:0,handoff:0});
    const bucket = days.get(day);
    bucket.total++;
    if (report.outcome in outcomes) bucket[report.outcome]++;
  }
  return [...days.values()].sort((a,b)=>a.day.localeCompare(b.day));
}
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
