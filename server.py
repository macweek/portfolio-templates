"""Suite locale de cinq applications : administration, commandes, stock, CSV, rendez-vous."""
import argparse, csv, hashlib, hmac, io, json, os, re, secrets, sqlite3, time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo
from automation.clean_contacts import clean_contacts
ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('DEMO_DB',str(ROOT/'data'/'applications.sqlite3')))
ZONE=ZoneInfo('Europe/Paris')
DEFAULT_SITE={'name':'Atelier Lisière','title':'Des espaces à votre mesure.','intro':'Meubles et aménagements sur mesure. Décrivez votre projet : nous vous répondrons depuis notre espace de gestion.','color':'#213c33','services':[{'name':'Étagères','price':450},{'name':'Bureau','price':1200},{'name':'Bibliothèque','price':2400}]}
DEFAULT_BUSINESS={'name':'','address':'','email':'','phone':'','registration':'','tax_note':'','iban':'','payment_terms':'Paiement à réception','invoice_footer':''}
SLOTS=['09:00','10:00','11:00','14:00','15:00','16:00']
SCHEMA="""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY CHECK(id=1), email TEXT NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,client TEXT NOT NULL,email TEXT NOT NULL,address TEXT NOT NULL,description TEXT NOT NULL,lines TEXT NOT NULL,discount INTEGER NOT NULL DEFAULT 0,tax INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'draft',delivery TEXT NOT NULL DEFAULT 'not_started',carrier TEXT NOT NULL DEFAULT '',tracking TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES orders(id),amount INTEGER NOT NULL CHECK(amount>0),kind TEXT NOT NULL,method TEXT NOT NULL,paid_on TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),number TEXT NOT NULL UNIQUE,year INTEGER NOT NULL,seq INTEGER NOT NULL,snapshot TEXT NOT NULL,issued_on TEXT NOT NULL,UNIQUE(year,seq));
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,name TEXT NOT NULL,sku TEXT NOT NULL COLLATE NOCASE UNIQUE,quantity INTEGER NOT NULL CHECK(quantity>=0 AND quantity<=1000000),threshold INTEGER NOT NULL DEFAULT 3,price INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY,product_id INTEGER NOT NULL REFERENCES products(id),delta INTEGER NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS csv_jobs(id INTEGER PRIMARY KEY,filename TEXT NOT NULL,kept INTEGER NOT NULL,duplicates INTEGER NOT NULL,rejected INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS reservations(id INTEGER PRIMARY KEY,day TEXT NOT NULL,slot TEXT NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,service TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'confirmed',token TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_slot ON reservations(day,slot) WHERE status!='cancelled';
"""
class Problem(Exception):
 def __init__(self,code,message):self.code,self.message=code,message

def connect():
 db=sqlite3.connect(DB,timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db

def init_db():
 DB.parent.mkdir(parents=True,exist_ok=True)
 with connect() as db:
  db.executescript(SCHEMA)
  for key,value in [('site',DEFAULT_SITE),('business',DEFAULT_BUSINESS),('booking',{'slots':SLOTS,'closed_days':[]})]:db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,json.dumps(value)))

 os.chmod(DB,0o600)

def setting(db,key):return json.loads(db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0])
def text(d,k,limit=200,required=True):
 v=d.get(k,'')
 if not isinstance(v,str) or len(v.strip())>limit or (required and not v.strip()):raise Problem(400,'Champ invalide : '+k)
 return v.strip()
def integer(v,low,high,label):
 if type(v) is not int or not low<=v<=high:raise Problem(400,'Valeur invalide : '+label)
 return v
def money(v):
 try:
  n=Decimal(str(v))
  if not n.is_finite() or not 0<=n<=Decimal('10000000'):raise ValueError()
  return int((n*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
 except (ValueError,InvalidOperation):raise Problem(400,'Montant invalide')
def email(v):
 if not isinstance(v,str) or len(v)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v.strip()):raise Problem(400,'Adresse email invalide')
 return v.strip().lower()
def rows(db,q,args=()):return [dict(r) for r in db.execute(q,args)]
def overlaps(a,b):return abs((int(a[:2])*60+int(a[3:]))-(int(b[:2])*60+int(b[3:])))<60
def today():return datetime.now(ZONE).date()
def order_data(db,oid):
 r=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
 if not r:raise Problem(404,'Commande introuvable')
 d=dict(r);d['lines']=json.loads(d['lines']);subtotal=sum(l['quantity']*l['unit_cents'] for l in d['lines']);discount=(subtotal*d['discount']+50)//100;net=subtotal-discount;tax=(net*d['tax']+50)//100
 d.update(subtotal=subtotal,discount_cents=discount,tax_cents=tax,total=net+tax)
 d['payments']=rows(db,'SELECT * FROM payments WHERE order_id=? ORDER BY id',(oid,));d['paid']=sum(x['amount'] for x in d['payments']);d['balance']=d['total']-d['paid'];inv=db.execute('SELECT id,number FROM invoices WHERE order_id=?',(oid,)).fetchone();d['invoice']=dict(inv) if inv else None
 return d

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'web'),**kw)
 def end_headers(self):
  self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin');self.send_header('X-Frame-Options','SAMEORIGIN');super().end_headers()
 def reply(self,status,data,cookie=None):
  raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
  if cookie:self.send_header('Set-Cookie',cookie)
  self.end_headers();self.wfile.write(raw)
 def cookie_name(self):return 'studio_session_'+str(self.server.server_port)
 def token(self):
  for part in self.headers.get('Cookie','').split(';'):
   if part.strip().startswith(self.cookie_name()+'='):return part.strip().split('=',1)[1]
  for part in self.headers.get('Cookie','').split(';'):
   if part.strip().startswith('session='):return part.strip()[8:]
  return ''
 def authenticated(self,db):return bool(db.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(self.token().encode()).hexdigest(),int(time.time()))).fetchone())
 def require(self,db):
  if not self.authenticated(db):raise Problem(401,'Connectez-vous à l’administration.')
 def body(self):
  if self.headers.get_content_type()!='application/json':raise Problem(415,'JSON requis')
  try:size=int(self.headers.get('Content-Length','0'))
  except ValueError:raise Problem(400,'Taille invalide')
  if not 0<size<=1500000:raise Problem(413,'Requête vide ou trop volumineuse')
  try:d=json.loads(self.rfile.read(size))
  except (ValueError,UnicodeError):raise Problem(400,'JSON invalide')
  if not isinstance(d,dict):raise Problem(400,'Objet JSON requis')
  return d
 def check_origin(self):
  if self.headers.get('Origin') and self.headers['Origin']!='http://'+self.headers.get('Host',''):raise Problem(403,'Origine refusée')
  if self.headers.get('Host','').split(':')[0] not in ('localhost','127.0.0.1'):raise Problem(403,'Hôte refusé')
 def do_GET(self):
  path=urlparse(self.path).path
  if not path.startswith('/api/'):
   return super().do_GET()
  self.dispatch('GET')
 def do_POST(self):self.dispatch('POST')
 def do_PATCH(self):self.dispatch('PATCH')
 def do_DELETE(self):self.dispatch('DELETE')
 def dispatch(self,method):
  try:
   self.check_origin();parsed=urlparse(self.path);path=parsed.path;query=parse_qs(parsed.query);data=self.body() if method in ('POST','PATCH') else {}
   with connect() as db:
    # Authentification : compte propriétaire unique, mot de passe haché et sessions expirantes.
    if path=='/api/session' and method=='GET':return self.reply(200,{'configured':bool(db.execute('SELECT 1 FROM users').fetchone()),'authenticated':self.authenticated(db)})
    if path in ('/api/setup','/api/login') and method=='POST':
     password=data.get('password');mail=email(data.get('email'))
     if not isinstance(password,str) or not 12<=len(password)<=256:raise Problem(400,'Mot de passe de 12 à 256 caractères requis')
     db.execute('BEGIN IMMEDIATE')
     user=db.execute('SELECT * FROM users').fetchone()
     if path=='/api/setup':
      if user:raise Problem(409,'Le compte administrateur existe déjà')
      salt=secrets.token_hex(24);hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex();db.execute('INSERT INTO users VALUES(1,?,?,?)',(mail,salt,hashed))
     else:
      key='login:'+self.client_address[0];attempts=LIMITS.setdefault(key,[]);attempts[:]=[v for v in attempts if time.time()-v<300]
      if len(attempts)>=10:raise Problem(429,'Trop de tentatives. Réessayez dans cinq minutes.')
      attempts.append(time.time())
      if not user or user['email']!=mail or not hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(user['salt']),600000).hex(),user['password']):raise Problem(401,'Email ou mot de passe incorrect')
      attempts.clear()
     token=secrets.token_urlsafe(32);db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),));db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),int(time.time())+43200));db.commit()
     return self.reply(200,{'authenticated':True},self.cookie_name()+'='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
    if path=='/api/logout' and method=='POST':
     db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(self.token().encode()).hexdigest(),));db.commit();return self.reply(200,{'ok':True},self.cookie_name()+'=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
    if path=='/api/booking-settings' and method=='GET':return self.reply(200,setting(db,'booking'))
    if path=='/api/site' and method=='GET':return self.reply(200,setting(db,'site'))
    if path=='/api/contact' and method=='POST':
     self.rate('contact',10);name=text(data,'name',100);mail=email(data.get('email'));message=text(data,'message',4000);db.execute('INSERT INTO contacts(name,email,message) VALUES(?,?,?)',(name,mail,message));db.commit();return self.reply(201,{'message':'Votre demande est enregistrée. Elle est disponible dans l’espace de gestion.'})
    if path=='/api/slots' and method=='GET':
     day=query.get('day',[str(today())])[0];self.valid_day(day);config=setting(db,'booking');closed=date.fromisoformat(day).weekday() in config['closed_days'];taken={r[0] for r in db.execute("SELECT slot FROM reservations WHERE day=? AND status!='cancelled'",(day,))};now=datetime.now(ZONE)
     return self.reply(200,[{'time':s,'available':not closed and not any(overlaps(s,t) for t in taken) and (day>str(today()) or s>now.strftime('%H:%M'))} for s in config['slots']])
    if path=='/api/reservations' and method=='POST':
     self.rate('reservation',20);day=text(data,'day',10);self.valid_day(day);slot=text(data,'slot',5);name=text(data,'name',100);mail=email(data.get('email'));service=text(data,'service',100)
     config=setting(db,'booking')
     if service not in [v['name'] for v in setting(db,'site')['services']]:raise Problem(400,'Prestation inconnue')
     if date.fromisoformat(day).weekday() in config['closed_days']:raise Problem(400,'La réservation est fermée ce jour-là')
     if slot not in config['slots'] or (day==str(today()) and slot<=datetime.now(ZONE).strftime('%H:%M')):raise Problem(400,'Choisissez un créneau à venir')
     db.execute('BEGIN IMMEDIATE')
     if any(overlaps(slot,r[0]) for r in db.execute("SELECT slot FROM reservations WHERE day=? AND status!='cancelled'",(day,))):raise Problem(409,'Ce créneau vient d’être réservé. Choisissez-en un autre.')
     token=secrets.token_urlsafe(24)
     try:cur=db.execute('INSERT INTO reservations(day,slot,name,email,service,token) VALUES(?,?,?,?,?,?)',(day,slot,name,mail,service,token));db.commit()
     except sqlite3.IntegrityError:raise Problem(409,'Ce créneau vient d’être réservé. Choisissez-en un autre.')
     return self.reply(201,{'id':cur.lastrowid,'day':day,'slot':slot,'token':token})
    if path=='/api/reservations/cancel' and method=='POST':
     self.rate('cancel',30);cur=db.execute("UPDATE reservations SET status='cancelled' WHERE id=? AND token=? AND status='confirmed'",(data.get('id'),data.get('token')));db.commit()
     if not cur.rowcount:raise Problem(404,'Réservation introuvable ou déjà traitée')
     return self.reply(200,{'ok':True})
    # Toutes les opérations de gestion suivantes sont réservées au propriétaire.
    self.require(db)
    if path=='/api/booking-settings' and method=='POST':
     slots=data.get('slots');closed=data.get('closed_days')
     if not isinstance(slots,list) or not 1<=len(slots)<=24 or any(not isinstance(v,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v) for v in slots):raise Problem(400,'Créneaux invalides (format HH:MM)')
     ordered=sorted(set(slots))
     minutes=[int(v[:2])*60+int(v[3:]) for v in ordered]
     if any(b-a<60 for a,b in zip(minutes,minutes[1:])):raise Problem(400,'Espacez les créneaux d’au moins une heure')
     if not isinstance(closed,list) or any(type(v) is not int or not 0<=v<=6 for v in closed):raise Problem(400,'Jours de fermeture invalides')
     val={'slots':ordered,'closed_days':sorted(set(closed))};db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(val),'booking'));db.commit();return self.reply(200,val)
    if path=='/api/business':
     if method=='GET':return self.reply(200,setting(db,'business'))
     if method=='POST':
      val={k:text(data,k,2000,False) for k in DEFAULT_BUSINESS};db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(val),'business'));db.commit();return self.reply(200,val)
    if path=='/api/site' and method=='POST':
     val={k:text(data,k,100 if k=='name' else 1000) for k in ('name','title','intro')};color=text(data,'color',7)
     if not re.fullmatch('#[0-9a-fA-F]{6}',color):raise Problem(400,'Couleur invalide')
     services=data.get('services')
     if not isinstance(services,list) or not 1<=len(services)<=10:raise Problem(400,'Entre une et dix prestations requises')
     val.update(color=color,services=[{'name':text(s,'name',100),'price':money(s.get('price'))/100} for s in services if isinstance(s,dict)])
     if len(val['services'])!=len(services):raise Problem(400,'Prestation invalide')
     db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(val),'site'));db.commit();return self.reply(200,val)
    if path=='/api/contacts' and method=='GET':return self.reply(200,rows(db,'SELECT * FROM contacts ORDER BY id DESC'))
    match=re.fullmatch(r'/api/contacts/(\d+)',path)
    if match and method=='PATCH':
     state=text(data,'status',20)
     if state not in ('new','handled','archived'):raise Problem(400,'Statut invalide')
     db.execute('UPDATE contacts SET status=? WHERE id=?',(state,int(match[1])));db.commit();return self.reply(200,{'ok':True})
    if path=='/api/orders':
     if method=='GET':return self.reply(200,[order_data(db,r[0]) for r in db.execute('SELECT id FROM orders ORDER BY id DESC')])
     if method=='POST':
      cur=db.execute("INSERT INTO orders(client,email,address,description,lines) VALUES('Nouveau client','','','Nouvelle commande','[]')");db.commit();return self.reply(201,order_data(db,cur.lastrowid))
    match=re.fullmatch(r'/api/orders/(\d+)(?:/(payments|invoice|delivery|progress))?',path)
    if match:
     oid=int(match[1]);action=match[2];db.execute('BEGIN IMMEDIATE');order=order_data(db,oid)
     if method=='GET' and not action:return self.reply(200,order)
     if method=='POST' and action=='progress':
      state=text(data,'state',20)
      if state not in ('draft','confirmed','in_progress','completed','archived'):raise Problem(400,'Statut invalide')
      db.execute('UPDATE orders SET state=? WHERE id=?',(state,oid));db.commit();return self.reply(200,order_data(db,oid))
     if method=='POST' and action=='delivery':
      delivery=text(data,'delivery',30)
      if delivery not in ('not_started','preparing','ready','shipped','delivered'):raise Problem(400,'Statut de livraison invalide')
      db.execute('UPDATE orders SET delivery=?,carrier=?,tracking=? WHERE id=?',(delivery,text(data,'carrier',100,False),text(data,'tracking',150,False),oid));db.commit();return self.reply(200,order_data(db,oid))
     if method=='POST' and action=='payments':
      amount=money(data.get('amount'));kind=text(data,'kind',20);method_name=text(data,'method',30);day=text(data,'paid_on',10)
      try:date.fromisoformat(day)
      except ValueError:raise Problem(400,'Date de règlement invalide')
      if kind not in ('deposit','balance','payment') or method_name not in ('transfer','card','cash','check','other'):raise Problem(400,'Type de règlement invalide')
      if amount<=0 or amount>order['balance']:raise Problem(409,'Le règlement doit être positif et ne pas dépasser le solde restant')
      if not order['lines'] or order['state']=='archived':raise Problem(409,'Enregistrez la commande avant le règlement')
      db.execute('INSERT INTO payments(order_id,amount,kind,method,paid_on,note) VALUES(?,?,?,?,?,?)',(oid,amount,kind,method_name,day,text(data,'note',500,False)));db.commit();return self.reply(201,order_data(db,oid))
     if method=='POST' and action=='invoice':
      if order['invoice']:raise Problem(409,'Cette commande a déjà une facture')
      business=setting(db,'business')
      if not business['name'] or not business['address']:raise Problem(400,'Renseignez le nom et l’adresse de l’émetteur dans les paramètres')
      if not order['lines'] or not order['address'] or order['total']<=0 or order['state']=='archived':raise Problem(400,'Renseignez les lignes et l’adresse de facturation avant émission')
      year=today().year;seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM invoices WHERE year=?',(year,)).fetchone()[0];number=f'F-{year}-{seq:04d}';snapshot={'order':order,'business':business}
      cur=db.execute('INSERT INTO invoices(order_id,number,year,seq,snapshot,issued_on) VALUES(?,?,?,?,?,?)',(oid,number,year,seq,json.dumps(snapshot),str(today())));db.execute("UPDATE orders SET state='confirmed' WHERE id=?",(oid,));db.commit();return self.reply(201,{'id':cur.lastrowid,'number':number})
     if method=='POST' and not action:
      if order['invoice']:raise Problem(409,'Facture émise : le contenu facturé est figé')
      lines=data.get('lines')
      if not isinstance(lines,list) or not 1<=len(lines)<=100:raise Problem(400,'Ajoutez entre une et cent lignes')
      normalized=[]
      for item in lines:
       if not isinstance(item,dict):raise Problem(400,'Ligne invalide')
       normalized.append({'label':text(item,'label',200),'quantity':integer(item.get('quantity'),1,10000,'quantité'),'unit_cents':money(item.get('unit_price'))})
      discount=integer(data.get('discount',0),0,100,'remise');tax=integer(data.get('tax',0),0,30,'TVA');state=text(data,'state',20)
      if state not in ('draft','confirmed','in_progress','completed','archived'):raise Problem(400,'Statut invalide')
      subtotal=sum(l['quantity']*l['unit_cents'] for l in normalized);net=subtotal-(subtotal*discount+50)//100;total=net+(net*tax+50)//100
      if total<order['paid']:raise Problem(409,'Le total ne peut pas être inférieur aux règlements reçus')
      db.execute('UPDATE orders SET client=?,email=?,address=?,description=?,lines=?,discount=?,tax=?,state=?,notes=? WHERE id=?',(text(data,'client',150),text(data,'email',254,False),text(data,'address',2000,False),text(data,'description',200),json.dumps(normalized),discount,tax,state,text(data,'notes',3000,False),oid));db.commit();return self.reply(200,order_data(db,oid))
    match=re.fullmatch(r'/api/invoices/(\d+)',path)
    if match and method=='GET':
     inv=db.execute('SELECT * FROM invoices WHERE id=?',(int(match[1]),)).fetchone()
     if not inv:raise Problem(404,'Facture introuvable')
     out=dict(inv);out['snapshot']=json.loads(out['snapshot']);out['payments']=order_data(db,out['order_id'])['payments'];return self.reply(200,out)
    if path=='/api/products':
     if method=='GET':return self.reply(200,rows(db,'SELECT * FROM products WHERE active=1 ORDER BY name'))
     if method=='POST':
      qty=integer(data.get('quantity'),0,1000000,'quantité');cur=db.execute('INSERT INTO products(name,sku,quantity,threshold,price) VALUES(?,?,?,?,?)',(text(data,'name',100),text(data,'sku',60),qty,integer(data.get('threshold',3),0,1000000,'seuil'),money(data.get('price',0))));db.execute('INSERT INTO movements(product_id,delta,reason) VALUES(?,?,?)',(cur.lastrowid,qty,'Stock initial'));db.commit();return self.reply(201,{'id':cur.lastrowid})
    match=re.fullmatch(r'/api/products/(\d+)(?:/(movements))?',path)
    if match:
     pid=int(match[1]);db.execute('BEGIN IMMEDIATE');product=db.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone()
     if not product:raise Problem(404,'Produit introuvable')
     if method=='POST' and match[2]:
      delta=integer(data.get('delta'),-1000000,1000000,'mouvement')
      if delta==0:raise Problem(400,'Mouvement non nul requis')
      if not 0<=product['quantity']+delta<=1000000:raise Problem(409,'Stock insuffisant ou capacité dépassée')
      db.execute('UPDATE products SET quantity=quantity+? WHERE id=?',(delta,pid));db.execute('INSERT INTO movements(product_id,delta,reason) VALUES(?,?,?)',(pid,delta,text(data,'reason',300)));db.commit();return self.reply(200,{'ok':True})
     if method=='PATCH':
      db.execute('UPDATE products SET name=?,sku=?,threshold=?,price=? WHERE id=?',(text(data,'name',100),text(data,'sku',60),integer(data.get('threshold'),0,1000000,'seuil'),money(data.get('price')),pid));db.commit();return self.reply(200,{'ok':True})
     if method=='DELETE':
      if product['quantity']!=0:raise Problem(409,'Le stock doit être à zéro avant archivage')
      db.execute('UPDATE products SET active=0 WHERE id=?',(pid,));db.commit();return self.reply(200,{'ok':True})
    if path=='/api/movements' and method=='GET':return self.reply(200,rows(db,'SELECT m.*,p.name,p.sku FROM movements m JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 200'))
    if path=='/api/clean-csv' and method=='POST':
     raw=data.get('csv')
     if not isinstance(raw,str):raise Problem(400,'Fichier CSV requis')
     try:result=clean_contacts(raw)
     except (ValueError,csv.Error) as exc:raise Problem(400,str(exc))
     db.execute('INSERT INTO csv_jobs(filename,kept,duplicates,rejected) VALUES(?,?,?,?)',(text(data,'filename',200,False) or 'collage.csv',result['kept'],result['duplicates'],len(result['rejected'])));db.commit();return self.reply(200,result)
    if path=='/api/csv-jobs' and method=='GET':return self.reply(200,rows(db,'SELECT * FROM csv_jobs ORDER BY id DESC LIMIT 30'))
    if path=='/api/reservations' and method=='GET':return self.reply(200,rows(db,'SELECT id,day,slot,name,email,service,status,created_at FROM reservations ORDER BY day DESC,slot'))
    match=re.fullmatch(r'/api/reservations/(\d+)',path)
    if match and method=='PATCH':
     state=text(data,'status',20)
     if state not in ('confirmed','completed','cancelled'):raise Problem(400,'Statut invalide')
     db.execute('BEGIN IMMEDIATE')
     existing=db.execute('SELECT * FROM reservations WHERE id=?',(int(match[1]),)).fetchone()
     if not existing:raise Problem(404,'Réservation introuvable')
     if state!='cancelled' and any(overlaps(existing['slot'],r[0]) for r in db.execute("SELECT slot FROM reservations WHERE day=? AND id!=? AND status!='cancelled'",(existing['day'],existing['id']))):raise Problem(409,'Ce rendez-vous chevaucherait une autre réservation')
     cur=db.execute('UPDATE reservations SET status=? WHERE id=?',(state,int(match[1])))
     if not cur.rowcount:raise Problem(404,'Réservation introuvable')
     db.commit();return self.reply(200,{'ok':True})
    if path=='/api/export' and method=='GET':
     return self.reply(200,{'exported_at':datetime.now(ZONE).isoformat(),'site':setting(db,'site'),'business':setting(db,'business'),'booking_settings':setting(db,'booking'),'contacts':rows(db,'SELECT * FROM contacts'),'orders':[order_data(db,r[0]) for r in db.execute('SELECT id FROM orders')],'invoices':rows(db,'SELECT * FROM invoices'),'products':rows(db,'SELECT * FROM products'),'movements':rows(db,'SELECT * FROM movements'),'reservations':rows(db,'SELECT id,day,slot,name,email,service,status,created_at FROM reservations'),'csv_jobs':rows(db,'SELECT * FROM csv_jobs')})
    raise Problem(404,'Route introuvable')
  except Problem as exc:self.reply(exc.code,{'error':exc.message})
  except sqlite3.IntegrityError:self.reply(409,{'error':'Cette référence ou ce créneau existe déjà'})
  except sqlite3.OperationalError:self.reply(503,{'error':'Base occupée. Réessayez dans un instant.'})
 def rate(self,kind,limit):
  key=kind+':'+self.client_address[0];values=LIMITS.setdefault(key,[]);values[:]=[v for v in values if time.time()-v<60]
  if len(values)>=limit:raise Problem(429,'Trop de demandes. Réessayez dans une minute.')
  values.append(time.time())
 def valid_day(self,value):
  try:d=date.fromisoformat(value)
  except (ValueError,TypeError):raise Problem(400,'Date invalide')
  if d<today() or d>today()+timedelta(days=365):raise Problem(400,'Choisissez une date dans les douze prochains mois')
LIMITS={}
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8765);args=parser.parse_args();init_db();server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
 print('Applications : http://localhost:'+str(args.port),flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
