import json, os, subprocess, sys, tempfile, time, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from automation.clean_contacts import clean_contacts
class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.port=18765
        cls.proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port',str(cls.port)],env={**os.environ,'DEMO_DB':cls.tmp.name+'/test.sqlite3'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                cls.call('/api/products');break
            except OSError: time.sleep(.05)
        else: raise RuntimeError('Serveur de test indisponible')
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate();cls.proc.wait(timeout=5);cls.tmp.cleanup()
    @classmethod
    def call(cls,path,data=None):
        req=Request('http://127.0.0.1:'+str(cls.port)+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
        try:
            with urlopen(req) as r:return r.status,json.load(r)
        except HTTPError as r:return r.code,json.load(r)
    def test_stock(self):
        code,p=self.call('/api/products',{'name':'Test unique','quantity':1});self.assertEqual(code,201)
        self.assertEqual(self.call('/api/products',{'name':'test unique','quantity':1})[0],409)
        self.assertEqual(self.call('/api/products',{'name':'Bad','quantity':True})[0],400)
        route='/api/products/'+str(p['id'])+'/movements'
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.call(route,{'delta':-1}),range(2)))
        self.assertEqual(sorted(r[0] for r in results),[200,409])
        self.assertEqual(self.call(route,{'delta':0})[0],400)
        self.assertEqual(self.call('/api/products/999999/movements',{'delta':1})[0],404)
        self.assertTrue(self.call('/api/movements')[1])
    def test_csv(self):
        result=clean_contacts('nom;email\n Alice ; ALICE@example.com \nAlice;alice@example.com\nBob;invalide\n=FORMULE;ok@example.com\n')
        self.assertEqual((result['kept'],result['duplicates'],len(result['rejected'])),(2,1,1))
        self.assertIn("'=FORMULE",result['csv'])
        self.assertRaises(ValueError,clean_contacts,'prenom;adresse\na;b')
        self.assertEqual(self.call('/api/clean-csv',{'csv':'nom,email\nBob,bob@example.com'})[1]['kept'],1)
    def test_static_and_errors(self):
        for path in ['/','/artisan/','/missions/','/stock/','/csv/','/booking.html']:
            with urlopen('http://127.0.0.1:'+str(self.port)+path) as r:self.assertEqual(r.status,200)
        self.assertEqual(self.call('/api/inconnue')[0],404)
        self.assertEqual(self.call('/api/products',{'name':'Bad','quantity':-1})[0],400)
if __name__=='__main__':unittest.main()
