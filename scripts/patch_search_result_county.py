from pathlib import Path

p=Path('north-america/app.js')
s=p.read_text()
old="    if(remote.length){rows.push('<div class=\"result-head\">Official lake registries</div>');remote.forEach(l=>rows.push(`<div class=\"result\" data-id=\"${escapeHtml(l.id)}\"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(l.region)} · ${escapeHtml(l.source)} · morphology auto-match</span></div>`));}\n"
new="    if(remote.length){rows.push('<div class=\"result-head\">Official lake database</div>');remote.forEach(l=>{const place=l.county?`${l.county} County · ${l.region}`:l.region;rows.push(`<div class=\"result\" data-id=\"${escapeHtml(l.id)}\"><b>${escapeHtml(l.name)}</b><span>${escapeHtml(place)} · ${escapeHtml(l.source)} · morphology auto-match</span></div>`);});}\n"
if old in s:
    s=s.replace(old,new,1)
elif "const place=l.county?" not in s:
    raise SystemExit('search result markup target not found')
p.write_text(s)
