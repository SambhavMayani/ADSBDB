'use strict';
const $=id=>document.getElementById(id);
let tab='text',busy=false;
const names= {
  images:'Imagen',audio:'Audio',text:'Texto'
};
let ragAssetsReady = false;
async function loadRagAssets() {
  if (ragAssetsReady) return;
  const {assets} = await api('/api/rag/assets');
  for (const [index, asset] of assets.entries()) {
    const option = element('option', asset.species_id.replaceAll('_', ' ') + ' · imagen ' + (index + 1));
    option.value = asset.source_key;
    $('rag-source').append(option);
  }
  ragAssetsReady = true;
}

function renderRag(result) {
  const area = $('generation');
  const failed = result.status === 'error';
  const badges = {answered: 'RAG · CITAS COMPROBADAS', partial: 'RAG · RESPUESTA PARCIAL', abstained: 'RAG · ABSTENCIÓN', error: 'RAG · ERROR DE GENERACIÓN'};
  area.replaceChildren(element('span', badges[result.status] || 'RAG', 'badge'),
    element('h2', ['answered','partial'].includes(result.status) ? 'Una respuesta, con sus fuentes.' :
      failed ? 'Fuentes recuperadas; respuesta sin completar o validar.' : 'Sin respuesta documental suficientemente respaldada.'));
  if (result.visual_candidates && result.visual_candidates.length) {
    const candidates = element('div', null, 'rag-candidates');
    candidates.append(element('strong', 'Candidatas recuperadas del corpus'));
    for (const candidate of result.visual_candidates) {
      candidates.append(element('p', candidate.common_name + ' · ' + candidate.scientific_name));
    }
    candidates.append(element('p', 'Asociaciones por similitud visual; no confirman la especie de la fotografía.', 'hint'));
    area.append(candidates);
  }
  if (result.claims.length) {
    for (const claim of result.claims) {
      const paragraph = element('p', claim.text + ' ');
      const citation = element('a', '[' + claim.source_id + ']');
      citation.href = '#source-' + claim.source_id;
      paragraph.append(citation);
      area.append(paragraph, element('blockquote', claim.quote));
    }
  } else area.append(element('p', result.answer));
  if (result.missing_aspects && result.missing_aspects.length) {
    const labels = {habitat:'hábitat',diet:'alimentación',behavior:'comportamiento',profile:'identificación de candidata'};
    area.append(element('p', 'Sin respuesta respaldada para: ' + result.missing_aspects.map(aspect => labels[aspect] || aspect).join(', '), 'hint'));
  }
  if (result.caption) area.append(element('p', 'Observación automática (BLIP): ' + result.caption, 'hint'));
  area.append(element('p', result.limitations, 'hint'));
  const trace = element('details');
  trace.append(element('summary', 'Cómo se ha construido esta respuesta'),
    element('p', 'Modelo: ' + result.model + ' · revisión ' + result.revision),
    element('p', 'Estado: ' + result.reason + ' · fuentes: ' + result.references.length),
    element('p', 'Consulta: ' + result.request_id),
    element('p', 'Las citas existen en las fuentes; esto no prueba por sí solo la interpretación del modelo.'));
  if (result.retrieval) trace.append(element('p', 'Contexto del generador: ' + result.retrieval.evidence_units +
    ' unidades · ' + result.retrieval.evidence_chars + ' caracteres de evidencia.'));
  if (result.generation) trace.append(element('p', 'Generación: ' + result.generation.input_tokens +
    ' tokens de entrada · ' + result.generation.output_tokens + ' de salida · ' +
    result.generation.generation_seconds + ' s · cierre: ' + result.generation.finish_reason +
    ' · límite de tiempo alcanzado: ' + (result.generation.deadline_reached ? 'sí' : 'no')));
  area.append(trace);
}
function element(tag,text,cls) {
  const n=document.createElement(tag);
  if(text)n.textContent=text;
  if(cls)n.className=cls;
  return n;
}
function message(text,error=false) {
  $('message').textContent=text;
  $('message').hidden=!text;
  $('message').className=error?'error':'';
}
async function api(path,payload) {
  const r=await fetch(path,payload? {
    method:'POST',headers: {
      'Content-Type':'application/json'
    },body:JSON.stringify(payload)
  }
  : {
  });
  const data=await r.json();
  if(!r.ok)throw new Error(data.error||'Servicio no disponible');
  return data;
}
function card(row) {
  const c=element('article',null,'card');
  if (row.citation_id) c.id = 'source-' + row.citation_id;
  const url='/api/media?key='+encodeURIComponent(row.source_key);
  if(row.modality==='images') {
    const img=element('img');
    img.src=url;
    img.alt=(row.species_id||'Fauna').replaceAll('_',' ');
    img.loading='lazy';
    c.append(img);
  } else c.append(element('div',row.modality==='audio'?'∿':'Aa',row.modality==='audio'?'audio-visual':'text-visual'));
  const body=element('div',null,'content');
  if (row.citation_id) body.append(element('strong', '[' + row.citation_id + ']'));
  body.append(element('span',(names[row.modality]||row.modality)+' / '+(row.space||''),'badge'),element('h3',(row.species_id||'Especie').replaceAll('_',' ')));
  if(row.modality==='audio') {
    const audio=element('audio');
    audio.src=url;
    audio.controls=true;
    audio.preload='none';
    body.append(audio);
  }
  if(row.snippet)body.append(element('p',row.snippet.slice(0,420)+(row.snippet.length>420?'…':'')));
  const details=element('details');
  details.append(element('summary','Fuente y trazabilidad'),element('p','Origen: '+row.source_name),element('p',row.source_key),element('p','Puntuación: '+Number(row.score).toFixed(4)+' ('+row.score_type+')'));
  if (row.excerpt) details.append(element('p', row.excerpt));
  body.append(details);
  for(const [label,flags] of [['Similares del mismo tipo ↗', {
    same_modality:true
  }
  ],['Relacionar con otros tipos ↗', {
    mixed:true
  }
  ]]) {
    const b=element('button',label);
    b.type='button';
    b.addEventListener('click',()=>run('/api/similar', {
      id:row.id,space:row.space,limit:8,species:$('species').value,...flags
    }));
    body.append(b);
  }
  c.append(body);
  return c;
}
async function run(path,payload) {
  if(busy)return;
  busy=true;
  $('submit').disabled=true;
  $('submit').textContent='Explorando…';
  message('Consultando el índice en CPU. La primera carga del modelo puede tardar.');
  $('results').replaceChildren();
  $('generation').hidden=true;
  const start=performance.now();
  try {
    let {
      results
    }
    =await api(path,payload);
    const generatedResult = !Array.isArray(results);
    if(generatedResult) {
      const g=$('generation');
      if (results.task === 'retrieval_augmented_generation') renderRag(results);
      else g.replaceChildren(element('span','DESCRIPCIÓN GENERADA · BLIP','badge'),element('h2',results.caption));
      g.hidden=false;
      results=results.references.map(row => ({...row, snippet: row.excerpt || row.snippet}));
    }
    $('result-title').textContent=generatedResult?'Fuentes recuperadas del corpus.':results.length?'Señales conectadas.':'Sin coincidencias para estos filtros.';
    $('result-meta').textContent=results.length+(generatedResult?' referencias · ':' activos · ')+((performance.now()-start)/1000).toFixed(1)+' s';
    message(results.length || generatedResult?'':'Prueba otra descripción o amplía los filtros.');
    $('results').replaceChildren(...results.map(card));
  } catch(e) {
    message(e.message,true);
  } finally {
    busy=false;
    $('submit').disabled=false;
    $('submit').textContent=tab==='generate'?'Responder con fuentes ↗':'Explorar ↗';
  }
}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=> {
  tab=b.dataset.tab;
  document.querySelectorAll('[data-tab]').forEach(x=> {
    x.classList.toggle('active',x===b);
    x.setAttribute('aria-pressed',String(x===b));
  });
  $('text-fields').hidden=tab!=='text';
  $('upload-fields').hidden=tab==='text';
  $('rag-fields').hidden=tab!=='generate';
  if (tab === 'generate') loadRagAssets().catch(error => message(error.message, true));
  const choices=tab==='text'?[['multimodal','Todas las modalidades'],['image_text','Imagen + texto · CLIP'],['audio_text','Audio + texto · CLAP'],['text','Task 1 · texto a texto · E5']]:tab==='media'?[['mono','Task 1 · misma modalidad'],['mixed','Task 2 · modalidades combinadas']]:[['rag','Recuperación → contexto → Qwen → citas']];
  $('mode').replaceChildren(...choices.map(([v,label])=> {
    const o=element('option',label);
    o.value=v;
    return o;
  }));
  $('mode').disabled=tab==='generate';
  $('filter').disabled=tab!=='text';
  $('species').disabled=tab==='generate';
  $('file').accept=tab==='generate'?'image/jpeg,image/png,image/webp':'image/jpeg,image/png,image/webp,audio/flac,audio/wav';
  document.querySelector('label[for="file"]').textContent=tab==='generate'?'Imagen de consulta opcional':'Imagen de referencia o audio breve';
  $('upload-hint').textContent=tab==='generate'?'Opcional: sube una imagen, elige una del corpus o pregunta solo por texto. Hasta 10 MB y 20 MP.':'Hasta 10 MB; audio hasta 30 segundos. La consulta no se guarda ni se indexa.';
  $('submit').textContent=tab==='generate'?'Responder con fuentes ↗':'Explorar ↗';
  $('method-note').textContent=tab==='generate'?'Las fuentes se recuperan antes de generar. Se comprueban citas literales. La falta de evidencia produce abstención; los fallos de generación se indican por separado.':'Las consultas no cambian el dataset. CLIP, CLAP y E5 se combinan por ranking, sin comparar sus distancias.';
}));
document.querySelectorAll('[data-query]').forEach(b=>b.addEventListener('click',()=> {
  $('query').value=b.dataset.query;
  $('query').focus();
}));
$('search-form').addEventListener('submit',async e=> {
  e.preventDefault();
  const common= {
    limit:8,species:$('species').value,filter:$('filter').value
  };
  if(tab==='text') {
    await run('/api/search', {
      ...common,query:$('query').value,mode:$('mode').value
    });
    return;
  }
  const f=$('file').files[0];
  if (tab === 'generate') {
    if ($('rag-question').value.trim().length < 3) { message('Escribe una pregunta para el corpus.', true); return; }
    if (f && f.size > 10 * 1024 * 1024) { message('El archivo supera 10 MB.', true); return; }
    try {
      const encoded = f ? await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = () => reject(new Error('No se pudo leer el archivo'));
        reader.readAsDataURL(f);
      }) : undefined;
      await run('/api/rag', {question: $('rag-question').value, source_key: $('rag-source').value || undefined, data: encoded});
    } catch (error) { message(error.message, true); }
    return;
  }
  if(!f) {
    message('Selecciona un archivo para continuar.',true);
    return;
  }
  if(f.size>10*1024*1024) {
    message('El archivo supera 10 MB.',true);
    return;
  }
  const data=await new Promise((resolve,reject)=> {
    const r=new FileReader();
    r.onload=()=>resolve(r.result.split(',')[1]);
    r.onerror=reject;
    r.readAsDataURL(f);
  });
  await run('/api/upload', {
    ...common,data,modality:f.type.startsWith('audio/')||/\.(flac|wav)$/i.test(f.name)?'audio':'images',mixed:$('mode').value==='mixed'
  });
});
$('rag-source').addEventListener('change', () => { if ($('rag-source').value) $('file').value = ''; });
$('file').addEventListener('change', () => { if ($('file').files.length) $('rag-source').value = ''; });
api('/api/status').then(s=> {
  const c=s.collections;
  $('total').textContent=Object.values(c).reduce((a,b)=>a+b,0).toLocaleString('es-ES');
  $('counts').replaceChildren(...[['images','imágenes'],['audio','ventanas de audio'],['text','fragmentos de texto']].map(([k,label])=>element('span',c[k]+' '+label)));
}).catch(()=>message('No se puede consultar el índice. Comprueba la instantánea y el servidor.',true));
