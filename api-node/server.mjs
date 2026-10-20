import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
const json = (res, status, body) => { res.writeHead(status, {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}); res.end(JSON.stringify(body)); };
export function createServer() {
  const slots = ['09:00','10:00','11:00','14:00','15:00','16:00'];
  const bookings = new Map();
  return http.createServer(async (req,res) => {
    const path = new URL(req.url,'http://localhost').pathname;
    if(req.headers.origin && req.headers.origin !== 'http://'+req.headers.host) return json(res,403,{error:'Origine refusée'});
    if(req.method==='GET' && path==='/') {
      res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
      return res.end(`<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Booking API — laboratoire</title><style>[hidden]{display:none!important}body{font:18px/1.6 Avenir,sans-serif;max-width:760px;margin:60px auto;padding:24px;background:#18392f;color:#f4f1e9}h1{font:56px Georgia}input,select,button{font:inherit;padding:12px;margin:8px 0;display:block}button{background:#d7ef80;border:0;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}label{display:block}a{color:#d7ef80}</style><p>DÉMONSTRATION · NODE.JS · DONNÉES EN MÉMOIRE</p><h1>Réservez un créneau.</h1><p>Créneaux fictifs pour une journée de démonstration. Aucun rendez-vous réel.</p><form id="book"><label>Votre nom fictif<input id="name" required maxlength="80"></label><label>Créneau<select id="slot"></select></label><button>Réserver</button></form><p id="result" role="status"></p><button id="cancel" hidden>Annuler ma dernière réservation</button><h2>Réponse API</h2><pre id="data"></pre><a href="/api/slots">Consulter les créneaux en JSON</a><script>let last;const status=document.querySelector('#result');async function load(){const r=await fetch('/api/slots'),d=await r.json();document.querySelector('#data').textContent=JSON.stringify(d,null,2);const sel=document.querySelector('#slot');sel.replaceChildren();d.filter(x=>x.available).forEach(x=>{const o=document.createElement('option');o.value=x.time;o.textContent=x.time;sel.append(o);});document.querySelector('#book button').disabled=!sel.options.length;}document.querySelector('#book').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{const r=await fetch('/api/bookings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.querySelector('#name').value,slot:document.querySelector('#slot').value})});const d=await r.json();if(!r.ok)throw Error(d.error);last=d.id;status.textContent='Réservation fictive confirmée pour '+d.slot;document.querySelector('#cancel').hidden=false;await load();}catch(e){status.textContent=e.message;}finally{await load();}};document.querySelector('#cancel').onclick=async()=>{const r=await fetch('/api/bookings/'+last,{method:'DELETE'});status.textContent=r.ok?'Réservation annulée.':'Annulation impossible.';if(r.ok)document.querySelector('#cancel').hidden=true;await load();};load().catch(()=>status.textContent='API indisponible.');</script></html>`);
    }
    if(req.method==='GET' && path==='/api/slots') return json(res,200,slots.map(time=>({time,available:!Array.from(bookings.values()).some(b=>b.slot===time)})));
    if(req.method==='POST' && path==='/api/bookings') {
      if(!(req.headers['content-type']||'').startsWith('application/json')) return json(res,415,{error:'Content-Type application/json requis'});
      let text='';
      try {
        for await (const chunk of req) { text+=chunk; if(Buffer.byteLength(text)>10000) return json(res,413,{error:'Requête trop volumineuse'}); }
        const data=JSON.parse(text);
        if(!data || typeof data.name!=='string' || !data.name.trim() || data.name.trim().length>80 || !slots.includes(data.slot)) return json(res,400,{error:'Nom (80 caractères maximum) et créneau valide requis'});
        if(Array.from(bookings.values()).some(b=>b.slot===data.slot)) return json(res,409,{error:'Créneau déjà réservé'});
        const booking={id:randomUUID(),name:data.name.trim(),slot:data.slot};bookings.set(booking.id,booking);return json(res,201,booking);
      } catch { return json(res,400,{error:'Corps JSON invalide'}); }
    }
    if(req.method==='DELETE' && path.startsWith('/api/bookings/')) {
      if(!bookings.delete(path.slice('/api/bookings/'.length))) return json(res,404,{error:'Réservation introuvable'});
      return json(res,200,{deleted:true});
    }
    json(res,404,{error:'Route inconnue'});
  });
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const port=Number(process.env.PORT||8766);
  createServer().listen(port,'127.0.0.1',()=>console.log('Booking API : http://localhost:'+port));
}
