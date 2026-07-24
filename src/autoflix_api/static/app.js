const $=s=>document.querySelector(s), provider=$('#provider'), query=$('#query'), results=$('#results'), message=$('#message'), video=$('#video'), empty=$('#screen-empty'), playerUrl=$('#player-url');
async function api(url, options){const r=await fetch(url,options);const data=await r.json();if(!r.ok){const error=new Error(data.error||'Erreur API');error.status=r.status;throw error}return data}
async function loadProviders(){const data=await api('/api/providers');provider.innerHTML=data.providers.map(p=>`<option value="${p.id}">${p.label}</option>`).join('')}
function setMessage(text,error=false){message.textContent=text;message.style.color=error?'var(--orange)':'var(--muted)'}
function collectPlayers(value, found=[]){
  if(!value||typeof value!=='object')return found;
  if(!Array.isArray(value)&&value.url&&value.name&&/^https?:\/\//i.test(value.url))found.push({name:value.name,url:value.url});
  if(Array.isArray(value))value.forEach(x=>collectPlayers(x,found));
  else Object.values(value).forEach(x=>collectPlayers(x,found));
  return found;
}
async function selectResult(item){
  playerUrl.value='';$('#now-playing').textContent=item.title||'Source sélectionnée';
  if(!item.url)return;
  setMessage('Chargement des lecteurs…');
  try{
    const data=await api(`/api/content?provider=${encodeURIComponent(provider.value)}&url=${encodeURIComponent(item.url)}`);
    const content=data.content;
    if(content.type==='movie')return renderPlayers(content.players);
    if(content.type==='series')return renderSeasons(content);
    if(content.type==='season')return renderEpisodes(content.episodes);
    setMessage('Type de contenu non reconnu.',true);
  }catch(e){setMessage(e.message,true)}
}
function renderPlayers(players){
  if(!players||!players.length){setMessage('Aucun lecteur exploitable trouvé.',true);return}
  setMessage(`${players.length} lecteur(s) trouvé(s). Choisissez une source.`);
  results.innerHTML=players.map((p,i)=>`<div class="result player-choice" data-i="${i}"><strong>${p.name}</strong><small>${new URL(p.url).hostname} · sélectionner cette source ↗</small></div>`).join('');
  results.querySelectorAll('.player-choice').forEach((el,i)=>el.onclick=()=>{playerUrl.value=players[i].url;$('#format').textContent='READY';setMessage(`Source « ${players[i].name} » sélectionnée. Cliquez sur RÉSOUDRE.`)});
  playerUrl.value=players[0].url;
}
function renderSeasons(content){
  const seasons=content.seasons||[];if(!seasons.length){setMessage('Aucune saison trouvée.',true);return}
  setMessage(`${seasons.length} saison(s) trouvée(s).`);
  results.innerHTML=seasons.map((s,i)=>`<div class="result season-choice" data-i="${i}"><strong>${s.title||`Saison ${i+1}`}</strong><small>${Object.values(s.episodes||{}).flat().length||'Charger'} épisode(s) · ouvrir ↗</small></div>`).join('');
  results.querySelectorAll('.season-choice').forEach((el,i)=>el.onclick=()=>openSeason(seasons[i]));
}
async function openSeason(season){
  try{
    let data=season;
    if(!Object.keys(season.episodes||{}).length){setMessage('Chargement des épisodes…');data=(await api(`/api/season?provider=${encodeURIComponent(provider.value)}&url=${encodeURIComponent(season.url)}`)).season}
    $('#now-playing').textContent=`${$('#now-playing').textContent} · ${data.title}`;renderEpisodes(data.episodes);
  }catch(e){setMessage(e.message,true)}
}
function renderEpisodes(byLanguage){
  const entries=Object.entries(byLanguage||{});const all=entries.flatMap(([language,items])=>items.map(item=>({...item,language})));
  if(!all.length){setMessage('Aucun épisode trouvé.',true);return}
  setMessage(`${all.length} épisode(s) trouvé(s).`);
  results.innerHTML=all.map((e,i)=>`<div class="result episode-choice" data-i="${i}"><strong>${e.title}</strong><small>${e.language.toUpperCase()} · ${e.players?.length||0} lecteur(s) · ouvrir ↗</small></div>`).join('');
  results.querySelectorAll('.episode-choice').forEach((el,i)=>el.onclick=()=>{ $('#now-playing').textContent=all[i].title; renderPlayers(all[i].players) });
}
$('#search').onclick=async()=>{const q=query.value.trim();if(q.length<2)return setMessage('Entrez au moins 2 caractères.',true);results.innerHTML='';setMessage('Scan en cours…');try{const data=await api(`/api/search?provider=${encodeURIComponent(provider.value)}&q=${encodeURIComponent(q)}`);if(!data.results.length){setMessage('Aucun résultat.');return}setMessage(`${data.results.length} résultat(s) trouvé(s).`);results.innerHTML=data.results.map((x,i)=>`<div class="result" data-i="${i}"><strong>${x.title||'Sans titre'}</strong><small>${(x.genres||[]).join(' · ')||'SOURCE'} ${x.url?'↗':''}</small></div>`).join('');results.querySelectorAll('.result').forEach((el,i)=>el.onclick=()=>selectResult(data.results[i]))}catch(e){setMessage(e.message,true)}};
query.onkeydown=e=>{if(e.key==='Enter')$('#search').click()};
$('#resolve').onclick=async()=>{const url=playerUrl.value.trim();const button=$('#resolve');if(!url)return setMessage('Sélectionnez d’abord un vrai lecteur.',true);button.disabled=true;button.textContent='RÉSOLUTION…';setMessage('Extraction du flux… cela peut prendre quelques secondes.');$('#format').textContent='FETCHING';try{const data=await api('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({player_url:url,referer:'https://french-stream.one/'})});const stream=data.stream_url;$('#format').textContent=(data.kind||'stream').toUpperCase();$('#resolved').innerHTML=`Flux résolu : <a href="${stream}" target="_blank" rel="noreferrer">ouvrir dans un nouvel onglet ↗</a>`;empty.style.display='none';video.classList.add('active');if(window.Hls&&Hls.isSupported()&&/\.m3u8/i.test(stream)){const hls=new Hls();hls.loadSource(stream);hls.attachMedia(video);hls.on(Hls.Events.MANIFEST_PARSED,()=>video.play().catch(()=>{}))}else{video.src=stream;video.play().catch(()=>{})}setMessage('Flux prêt.')}catch(e){$('#format').textContent='ERROR';const detail=e.status===404?'Ce lecteur ne fournit plus de flux compatible. Essayez une autre source.':e.status===502?'Le lecteur tiers répond lentement ou bloque la résolution. Attendez puis essayez une autre source.':e.message;setMessage(detail,true);$('#resolved').textContent=''}finally{button.disabled=false;button.textContent='RÉSOUDRE'}};
loadProviders().catch(e=>setMessage(e.message,true));
