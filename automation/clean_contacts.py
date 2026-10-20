"""Nettoyage CSV autonome, sans dépendance externe."""
import argparse, csv, io, json, re
from pathlib import Path

def clean_contacts(text):
    if len(text.encode('utf-8')) > 1000000:
        raise ValueError('CSV trop volumineux (maximum 1 Mo).')
    text = text.lstrip('\ufeff')
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError('CSV vide.')
    headers = [h.strip().lower() for h in reader.fieldnames]
    if len(set(headers)) != len(headers) or not {'nom', 'email'}.issubset(headers):
        raise ValueError('Colonnes nom et email requises, sans en-têtes en double.')
    reader.fieldnames = headers
    kept, rejected, seen, duplicates = [], [], set(), 0
    for row in reader:
        line = reader.line_num
        if None in row or any(v is None for v in row.values()):
            rejected.append({'line': line, 'reason': 'Nombre de colonnes incorrect'})
            continue
        name = ' '.join(row['nom'].split())
        email = row['email'].strip().lower()
        if not name or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            rejected.append({'line': line, 'reason': 'Nom manquant ou email invalide'})
            continue
        if email in seen:
            duplicates += 1
            continue
        seen.add(email)
        kept.append({'nom': name, 'email': email})
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=['nom', 'email'])
    writer.writeheader()
    # Neutralise les formules de tableur dans les valeurs exportées.
    def safe(value):
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    writer.writerows({k: safe(v) for k,v in row.items()} for row in kept)
    return {'csv': output.getvalue(), 'kept': len(kept), 'duplicates': duplicates, 'rejected': rejected}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Le fichier de sortie doit être différent du fichier source.')
    try:
        result = clean_contacts(args.input.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        parser.exit(1, str(exc)+'\n')
    args.output.write_text(result.pop('csv'), encoding='utf-8-sig')
    args.output.with_suffix('.report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
