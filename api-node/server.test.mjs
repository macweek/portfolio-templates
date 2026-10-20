import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from './server.mjs';
test('réservation, conflit simultané, annulation et validation',async()=>{
 const server=createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
 try {
 const post=(body)=>fetch(url+'/api/bookings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 assert.equal((await post({name:'',slot:'09:00'})).status,400);
 assert.equal((await post(null)).status,400);
 const responses=await Promise.all([post({name:'Alice',slot:'09:00'}),post({name:'Bob',slot:'09:00'})]);assert.deepEqual(responses.map(r=>r.status).sort(),[201,409]);
 const booking=await responses.find(r=>r.status===201).json();
 let slots=await (await fetch(url+'/api/slots')).json();assert.equal(slots.find(s=>s.time==='09:00').available,false);
 assert.equal((await fetch(url+'/api/bookings/'+booking.id,{method:'DELETE'})).status,200);
 assert.equal((await fetch(url+'/api/bookings/'+booking.id,{method:'DELETE'})).status,404);
 slots=await (await fetch(url+'/api/slots')).json();assert.equal(slots.find(s=>s.time==='09:00').available,true);
 assert.equal((await fetch(url+'/api/bookings',{method:'POST',headers:{'Content-Type':'application/json'},body:'{'})).status,400);
 } finally {await new Promise(r=>server.close(r));}
});
