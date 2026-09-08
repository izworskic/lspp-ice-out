(() => {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : input?.url;
    if (typeof url === 'string' && /\/lake-index\/[a-z0-9_]{2}\.json(?:$|\?)/i.test(url)) {
      const q = document.getElementById('search')?.value?.trim() || '';
      if (q.length >= 2) {
        return nativeFetch(`/api/lake-search?q=${encodeURIComponent(q)}`, { cache: 'no-store' })
          .then(async r => {
            if (!r.ok) return nativeFetch(input, init);
            const j = await r.json();
            if (!Array.isArray(j.rows)) return nativeFetch(input, init);
            return new Response(JSON.stringify(j.rows), {
              status: 200,
              headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }
            });
          })
          .catch(() => nativeFetch(input, init));
      }
    }
    return nativeFetch(input, init);
  };
})();
