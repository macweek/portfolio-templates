"""Serveur de démonstration local : interface, stock SQLite et nettoyage CSV."""
import argparse, json, os, re, sqlite3
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from automation.clean_contacts import clean_contacts
ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('DEMO_DB', str(ROOT / 'data' / 'demo.sqlite3')))

def connect():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, quantity INTEGER NOT NULL CHECK(quantity >= 0 AND quantity <= 1000000)); CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), delta INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);')
        if not db.execute('SELECT COUNT(*) FROM products').fetchone()[0]:
            db.executemany('INSERT INTO products(name,quantity) VALUES(?,?)', [('Carnet kraft',24),('Stylo rechargeable',12),('Pochette coton',8)])

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT/'web'), **kwargs)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        super().end_headers()

    def reply(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ['/api/products', '/api/movements']:
            with connect() as db:
                query = 'SELECT * FROM products ORDER BY id' if path.endswith('products') else 'SELECT * FROM movements ORDER BY id DESC LIMIT 100'
                rows = [dict(r) for r in db.execute(query)]
            self.reply(200, rows)
        elif path.startswith('/api/'):
            self.reply(404, {'error':'Route inconnue'})
        else:
            super().do_GET()

    def do_POST(self):
        # Refuse les requêtes intersites vers ce service local.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.reply(403, {'error':'Origine refusée'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error':'Content-Type application/json requis'})
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 1200000:
                return self.reply(413, {'error':'Requête vide ou trop volumineuse'})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Objet JSON requis')
            path = self.path.split('?')[0]
            if path == '/api/clean-csv':
                if not isinstance(data.get('csv'), str):
                    raise ValueError('Champ csv requis')
                return self.reply(200, clean_contacts(data['csv']))
            if path == '/api/products':
                name, qty = data.get('name'), data.get('quantity')
                if not isinstance(name,str) or not 1 <= len(name.strip()) <= 100 or type(qty) is not int or not 0 <= qty <= 1000000:
                    raise ValueError('Nom requis (100 caractères maximum) et quantité entière entre 0 et 1000000')
                with connect() as db:
                    cur = db.execute('INSERT INTO products(name,quantity) VALUES(?,?)', (name.strip(),qty))
                    db.execute('INSERT INTO movements(product_id,delta) VALUES(?,?)', (cur.lastrowid,qty))
                    product = dict(db.execute('SELECT * FROM products WHERE id=?',(cur.lastrowid,)).fetchone())
                return self.reply(201, product)
            match = re.fullmatch(r'/api/products/(\d+)/movements', path)
            if match:
                delta = data.get('delta')
                if type(delta) is not int or delta == 0 or abs(delta) > 1000000:
                    raise ValueError('Mouvement entier non nul requis, maximum 1000000')
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    product = db.execute('SELECT * FROM products WHERE id=?', (int(match[1]),)).fetchone()
                    if not product:
                        return self.reply(404, {'error':'Produit introuvable'})
                    if not 0 <= product['quantity'] + delta <= 1000000:
                        return self.reply(409, {'error':'Stock insuffisant ou capacité maximale dépassée'})
                    db.execute('UPDATE products SET quantity=quantity+? WHERE id=?', (delta,product['id']))
                    db.execute('INSERT INTO movements(product_id,delta) VALUES(?,?)', (product['id'],delta))
                    updated = dict(db.execute('SELECT * FROM products WHERE id=?',(product['id'],)).fetchone())
                return self.reply(200, updated)
            self.reply(404, {'error':'Route inconnue'})
        except sqlite3.IntegrityError:
            self.reply(409, {'error':'Référence déjà existante ou contrainte de stock non respectée'})
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {'error':str(exc)})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    init_db()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print('Portfolio : http://localhost:'+str(args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
