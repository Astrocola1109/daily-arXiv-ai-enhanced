export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function safeArxivUrl(id) {
  if (!/^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?$/.test(id)) return '#';
  return `https://arxiv.org/abs/${id}`;
}
export function filterPapers(papers, states, tab, query='') {
  return papers.filter(p => {
    const s = states[p.id] ?? {};
    if (tab === 'favorite' && !s.favorite) return false;
    if (tab === 'read' && !s.is_read) return false;
    if (tab === 'disliked' && !s.disliked) return false;
    if (!['disliked','favorite','read','all'].includes(tab) && s.disliked) return false;
    if (tab === 'direct' && (p.relevance !== 'direct' || p.event === 'revision')) return false;
    if (tab === 'extension' && (p.relevance !== 'extension' || p.event === 'revision')) return false;
    if (tab === 'revision' && p.event !== 'revision') return false;
    if (tab === 'other' && p.relevance !== 'unrelated') return false;
    return `${p.title} ${(p.authors ?? []).join(' ')} ${(p.categories ?? []).join(' ')}`.toLowerCase().includes(query.toLowerCase());
  });
}
