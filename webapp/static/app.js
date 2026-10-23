'use strict';
const $=id=>document.getElementById(id);
let tab='text',busy=false;
const names= {
  images:'Imagen',audio:'Audio',text:'Texto'
};
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
  const url='/api/media?key='+encodeURIComponent(row.source_key);
  if(row.modality==='images') {
    const img=element('img');
    img.src=url;
    img.alt=(row.species_id||'Fauna').replaceAll('_',' ');
    img.loading='lazy';
    c.append(img);
  } else c.append(element('div',row.modality==='audio'?'∿':'Aa',row.modality==='audio'?'audio-visual':'text-visual'));
  const body=element('div',null,'content');
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
    if(!Array.isArray(results)) {
      const g=$('generation');
      g.replaceChildren(element('span','DESCRIPCIÓN GENERADA · BLIP','badge'),element('h2',results.caption),element('p','Descripción automática en inglés; no certifica la especie. Las referencias siguientes permiten contrastarla.'));
      g.hidden=false;
      results=results.references;
    }
    $('result-title').textContent=results.length?'Señales conectadas.':'Sin coincidencias para estos filtros.';
    $('result-meta').textContent=results.length+' activos · '+((performance.now()-start)/1000).toFixed(1)+' s';
    message(results.length?'':'Prueba otra descripción o amplía los filtros.');
    $('results').replaceChildren(...results.map(card));
  } catch(e) {
    message(e.message,true);
  } finally {
    busy=false;
    $('submit').disabled=false;
    $('submit').textContent=tab==='generate'?'Describir ↗':'Explorar ↗';
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
  const choices=tab==='text'?[['multimodal','Todas las modalidades'],['image_text','Imagen + texto · CLIP'],['audio_text','Audio + texto · CLAP'],['text','Task 1 · texto a texto · E5']]:tab==='media'?[['mono','Task 1 · misma modalidad'],['mixed','Task 2 · modalidades combinadas']]:[['generate','BLIP → CLIP · descripción y referencias']];
  $('mode').replaceChildren(...choices.map(([v,label])=> {
    const o=element('option',label);
    o.value=v;
    return o;
  }));
  $('mode').disabled=tab==='generate';
  $('filter').disabled=tab!=='text';
  $('species').disabled=tab==='generate';
  $('file').accept=tab==='generate'?'image/jpeg,image/png,image/webp':'image/jpeg,image/png,image/webp,audio/flac,audio/wav';
  document.querySelector('label[for="file"]').textContent=tab==='generate'?'Imagen para describir':'Imagen de referencia o audio breve';
  $('upload-hint').textContent=tab==='generate'?'Imagen de hasta 10 MB y 20 megapíxeles. La consulta no se guarda ni se indexa.':'Hasta 10 MB; audio hasta 30 segundos. La consulta no se guarda ni se indexa.';
  $('submit').textContent=tab==='generate'?'Describir ↗':'Explorar ↗';
  $('method-note').textContent=tab==='generate'?'Un modelo BLIP genera la descripción; CLIP recupera referencias. El modelo debe estar preparado en la caché local.':'Las consultas no cambian el dataset. CLIP, CLAP y E5 se combinan por ranking, sin comparar sus distancias.';
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
  await run(tab==='generate'?'/api/describe':'/api/upload', {
    ...common,data,modality:f.type.startsWith('audio/')||/\.(flac|wav)$/i.test(f.name)?'audio':'images',mixed:$('mode').value==='mixed'
  });
});
api('/api/status').then(s=> {
  const c=s.collections;
  $('total').textContent=Object.values(c).reduce((a,b)=>a+b,0).toLocaleString('es-ES');
  $('counts').replaceChildren(...[['images','imágenes'],['audio','ventanas de audio'],['text','fragmentos de texto']].map(([k,label])=>element('span',c[k]+' '+label)));
}).catch(()=>message('No se puede consultar el índice. Comprueba la instantánea y el servidor.',true));
