import json, os, socket, subprocess, sys, tempfile, time, unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from automation.clean_contacts import clean_contacts
class ApplicationsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.cookie=''
  with socket.socket() as sock:
   sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
  cls.proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port',str(cls.port)],env={**os.environ,'DEMO_DB':cls.tmp.name+'/test.sqlite3'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  cls.addClassCleanup(lambda: cls.proc.poll() is None and (cls.proc.terminate(), cls.proc.wait(timeout=5)))
  for _ in range(100):
   try:cls.call('/api/session');break
   except OSError:time.sleep(.05)
  else:
   cls.proc.terminate();raise RuntimeError('Serveur de test indisponible')
  status,data,cookie=cls.call('/api/setup',{'email':'owner@example.com','password':'Temporary-test-password-2026'},raw=True)
  if status!=200:raise RuntimeError(data)
  cls.cookie=cookie.split(';')[0]
 @classmethod
 def tearDownClass(cls):
  cls.proc.terminate();cls.proc.wait(timeout=5);cls.tmp.cleanup()
 @classmethod
 def call(cls,path,data=None,method=None,auth=True,raw=False,headers=None):
  h={'Content-Type':'application/json'}
  if auth and cls.cookie:h['Cookie']=cls.cookie
  h.update(headers or {})
  req=Request('http://127.0.0.1:'+str(cls.port)+path,data=json.dumps(data).encode() if data is not None else None,method=method or ('POST' if data is not None else 'GET'),headers=h)
  try:
   with urlopen(req,timeout=10) as r:
    result=(r.status,json.load(r),r.headers.get('Set-Cookie',''))
  except HTTPError as r:result=(r.code,json.load(r),r.headers.get('Set-Cookie',''))
  return result if raw else result[:2]
 def create_order(self):
  code,o=self.call('/api/orders',{});self.assertEqual(code,201)
  data={'client':'Alice Exemple','email':'alice@example.com','address':'1 rue Exemple','description':'Site vitrine','lines':[{'label':'Site','quantity':1,'unit_price':100},{'label':'Maintenance','quantity':2,'unit_price':25}],'discount':10,'tax':20,'state':'confirmed','notes':''}
  code,o=self.call('/api/orders/'+str(o['id']),data);self.assertEqual(code,200);return o,data
 def test_authentication_and_origin(self):
  self.assertEqual(self.call('/api/orders',auth=False)[0],401)
  self.assertEqual(self.call('/api/setup',{'email':'other@example.com','password':'Temporary-test-password-2026'},auth=False)[0],409)
  self.assertEqual(self.call('/api/login',{'email':'owner@example.com','password':'wrong-password-long'},auth=False)[0],401)
  self.assertEqual(self.call('/api/orders',{},headers={'Origin':'http://example.com'})[0],403)
  self.assertEqual(self.call('/api/session',auth=False)[1]['authenticated'],False)
  self.assertEqual(self.call('/api/session')[1]['authenticated'],True)
 def test_order_payments_invoice_delivery(self):
  o,data=self.create_order();self.assertEqual((o['subtotal'],o['discount_cents'],o['tax_cents'],o['total']),(15000,1500,2700,16200))
  route='/api/orders/'+str(o['id'])
  payment={'amount':50,'kind':'deposit','method':'transfer','paid_on':str(date.today()),'note':'ACOMPTE-1'}
  code,o=self.call(route+'/payments',payment);self.assertEqual(code,201);self.assertEqual((o['paid'],o['balance']),(5000,11200))
  self.assertEqual(self.call(route+'/payments',{**payment,'amount':200})[0],409)
  self.assertEqual(self.call(route+'/payments',{**payment,'amount':-1})[0],400)
  self.assertEqual(self.call(route+'/invoice',{})[0],400)
  self.call('/api/business',{'name':'Société test','address':'1 rue Test'})
  code,inv=self.call(route+'/invoice',{});self.assertEqual(code,201)
  self.assertEqual(self.call(route,data)[0],409)
  self.assertEqual(self.call(route+'/invoice',{})[0],409)
  code,o=self.call(route+'/delivery',{'delivery':'shipped','carrier':'Test','tracking':'ABC-123'});self.assertEqual(code,200);self.assertEqual(o['delivery'],'shipped')
  self.assertEqual(self.call(route+'/progress',{'state':'completed'})[1]['state'],'completed')
  code,o=self.call(route+'/payments',{**payment,'amount':112,'kind':'balance'});self.assertEqual(code,201);self.assertEqual(o['balance'],0)
  invoice=self.call('/api/invoices/'+str(inv['id']))[1];self.assertEqual(invoice['snapshot']['order']['total'],16200)
  self.assertEqual(sum(p['amount'] for p in invoice['payments']),16200)
  self.call('/api/business',{'name':'Nouveau nom','address':'Autre adresse'})
  self.assertEqual(self.call('/api/invoices/'+str(inv['id']))[1]['snapshot']['business']['name'],'Société test')
 def test_concurrent_payment_no_overpayment(self):
  o,_=self.create_order();route='/api/orders/'+str(o['id'])+'/payments';p={'amount':100,'kind':'payment','method':'transfer','paid_on':str(date.today())}
  with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.call(route,p),range(2)))
  self.assertEqual(sorted(x[0] for x in results),[201,409])
 def test_stock_and_history(self):
  code,p=self.call('/api/products',{'name':'Clavier','sku':'KEY-01','quantity':1,'threshold':3,'price':25});self.assertEqual(code,201)
  self.assertEqual(self.call('/api/products',{'name':'Clavier','sku':'key-01','quantity':1})[0],409)
  self.assertEqual(self.call('/api/products',{'name':'Bad','sku':'BAD','quantity':True})[0],400)
  route='/api/products/'+str(p['id'])
  with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.call(route+'/movements',{'delta':-1,'reason':'Livraison'}),range(2)))
  self.assertEqual(sorted(x[0] for x in results),[200,409])
  self.assertEqual(self.call(route,{'name':'Clavier modifié','sku':'KEY-01','threshold':2,'price':30},'PATCH')[0],200)
  self.assertEqual(self.call(route,method='DELETE')[0],200)
  self.assertTrue(self.call('/api/movements')[1])
 def test_site_contact_and_settings(self):
  content={'name':'Atelier Test','title':'Un autre titre','intro':'Présentation personnalisée','color':'#234567','services':[{'name':'Conseil','price':80}]}
  self.assertEqual(self.call('/api/site',content)[0],200)
  self.assertEqual(self.call('/api/site',auth=False)[1]['title'],'Un autre titre')
  self.assertEqual(self.call('/api/contact',{'name':'Alice','email':'alice@example.com','message':'Ma demande'},auth=False)[0],201)
  contacts=self.call('/api/contacts')[1];self.assertEqual(contacts[0]['message'],'Ma demande')
  self.assertEqual(self.call('/api/contacts/'+str(contacts[0]['id']),{'status':'handled'},'PATCH')[0],200)
 def test_booking_conflicts_and_cancel(self):
  d=str(date.today()+timedelta(days=2));payload={'day':d,'slot':'10:00','name':'Alice','email':'alice@example.com','service':'Étagères'}
  with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.call('/api/reservations',payload,auth=False),range(2)))
  self.assertEqual(sorted(x[0] for x in results),[201,409]);booking=next(r[1] for r in results if r[0]==201)
  self.assertEqual(next(s for s in self.call('/api/slots?day='+d,auth=False)[1] if s['time']=='10:00')['available'],False)
  self.assertEqual(self.call('/api/reservations/cancel',{'id':booking['id'],'token':'bad'},auth=False)[0],404)
  self.assertEqual(self.call('/api/reservations/cancel',{'id':booking['id'],'token':booking['token']},auth=False)[0],200)
  self.assertEqual(next(s for s in self.call('/api/slots?day='+d,auth=False)[1] if s['time']=='10:00')['available'],True)
 def test_csv_and_export(self):
  result=clean_contacts('nom;email\n Alice ; ALICE@example.com \nAlice;alice@example.com\nBob;invalide\n=FORMULE;ok@example.com\n')
  self.assertEqual((result['kept'],result['duplicates'],len(result['rejected'])),(2,1,1));self.assertIn("'=FORMULE",result['csv'])
  self.assertRaises(ValueError,clean_contacts,'prenom;adresse\na;b')
  self.assertEqual(self.call('/api/clean-csv',{'filename':'test.csv','csv':'nom,email\nBob,bob@example.com'})[1]['kept'],1)
  self.assertEqual(self.call('/api/csv-jobs')[1][0]['kept'],1)
  exported=self.call('/api/export')[1];self.assertNotIn('sessions',exported);self.assertNotIn('users',exported)
 def test_pages(self):
  for path in ['/','/admin.html','/artisan/','/missions/','/invoice.html','/stock/','/csv/','/booking.html']:
   with urlopen('http://127.0.0.1:'+str(self.port)+path,timeout=5) as r:self.assertEqual(r.status,200)
  self.assertEqual(self.call('/api/unknown')[0],404)
 def test_booking_configuration_and_overlap(self):
  config=self.call('/api/booking-settings')[1]
  day_value=str(date.today()+timedelta(days=3))
  service=self.call('/api/site',auth=False)[1]['services'][0]['name']
  try:
   self.assertEqual(self.call('/api/booking-settings',{'slots':['10:00','10:30'],'closed_days':[]})[0],400)
   self.assertEqual(self.call('/api/booking-settings',{'slots':['10:00','11:00'],'closed_days':[]})[0],200)
   payload={'day':day_value,'slot':'10:00','name':'Test','email':'test@example.com','service':service}
   self.assertEqual(self.call('/api/reservations',payload,auth=False)[0],201)
   self.call('/api/booking-settings',{'slots':['10:30','11:30'],'closed_days':[]})
   self.assertEqual(self.call('/api/slots?day='+day_value,auth=False)[1][0]['available'],False)
   self.assertEqual(self.call('/api/reservations',{**payload,'slot':'10:30'},auth=False)[0],409)
   weekday=date.fromisoformat(day_value).weekday()
   self.call('/api/booking-settings',{'slots':['10:30','11:30'],'closed_days':[weekday]})
   self.assertTrue(all(not v['available'] for v in self.call('/api/slots?day='+day_value,auth=False)[1]))
  finally:self.call('/api/booking-settings',config)
 def test_z_persistence_after_restart(self):
  o,_=self.create_order();before=self.call('/api/orders/'+str(o['id']))[1]
  cls=type(self);cls.proc.terminate();cls.proc.wait(timeout=5)
  cls.proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port',str(cls.port)],env={**os.environ,'DEMO_DB':cls.tmp.name+'/test.sqlite3'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for _ in range(100):
   try:
    after=self.call('/api/orders/'+str(o['id']))
    if after[0]==200:break
   except OSError:pass
   time.sleep(.05)
  else:self.fail('Redémarrage impossible')
  self.assertEqual(after[1]['total'],before['total'])
  self.assertEqual(after[1]['client'],before['client'])
if __name__=='__main__':unittest.main()
