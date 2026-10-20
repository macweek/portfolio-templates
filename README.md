# Macweek — cinq démonstrations pour petites missions

Sites vitrines, outils internes, API et automatisation de fichiers. Réalisations de démonstration, conçues avec une assistance IA et vérifiées par des tests fonctionnels. Aucune référence client fictive présentée comme réelle.

**Prestations exclusivement à distance, réalisées depuis un Mac.**

## Démarrer sur Mac

Prérequis : Python 3.9+ et, pour Booking API, Node.js 20+. Aucune bibliothèque externe à installer. Les commandes sont à exécuter dans ce dossier.

```sh
python3 server.py
```

Ouvrir **http://localhost:8765**. Le serveur écoute uniquement sur la machine locale. Arrêt : `Ctrl+C`.

Pour le laboratoire Node.js, dans un second terminal :

```sh
node api-node/server.mjs
```

Ouvrir **http://localhost:8766**. Les deux serveurs sont indépendants.

## Les projets

| Projet | Besoin client illustré | Technologies | Démonstration |
|---|---|---|---|
| Atelier Lisière | Site vitrine artisan, qualification de demande | HTML, CSS responsive, JavaScript | `/artisan/` |
| Mission Desk | Suivi de petites missions et de leur progression | JavaScript, LocalStorage, export JSON | `/missions/` |
| Stock Clair | Inventaire et intégration avec une API | Python, SQLite, HTTP REST | `/stock/` |
| CSV Propre | Réduction des tâches de nettoyage manuel | Python, CSV, interface web et CLI | `/csv/` |
| Booking API | Réservation de créneaux avec gestion des conflits | Node.js, API REST, tests natifs | `/booking.html` puis port 8766 |

## Tests

```sh
python3 -m unittest discover -s tests -v
node --test api-node/server.test.mjs
```

Les tests Python démarrent un serveur temporaire sur le port 18765 et utilisent une base temporaire : aucune donnée de démonstration n’est modifiée. Ils couvrent notamment les sorties de stock concurrentes, les quantités invalides, les doublons et les CSV. Les tests Node couvrent le conflit entre deux réservations du même créneau, l’annulation et les requêtes invalides.

## API Stock Clair

```sh
curl http://localhost:8765/api/products
curl -X POST http://localhost:8765/api/products -H 'Content-Type: application/json' -d '{"name":"Clavier","quantity":5}'
curl -X POST http://localhost:8765/api/products/1/movements -H 'Content-Type: application/json' -d '{"delta":-1}'
curl http://localhost:8765/api/movements
```

`POST /api/products` : 201 si créé, 400 si invalide, 409 si le nom existe. `POST /api/products/:id/movements` : 200 si enregistré, 404 si absent, 409 si le stock dépasserait les limites. Quantités entières entre 0 et 1 000 000. Historique limité aux 100 derniers mouvements. Les références initiales sont des exemples et leur stock initial n’est pas inclus dans l’historique des mouvements.

Base créée automatiquement dans `data/demo.sqlite3`, exclue de Git. Pour réinitialiser, arrêter le serveur puis déplacer ce fichier. Une base vide est ensuite recréée au lancement. `DEMO_DB` permet de choisir un autre chemin.

## API Booking

```sh
curl http://localhost:8766/api/slots
curl -X POST http://localhost:8766/api/bookings -H 'Content-Type: application/json' -d '{"name":"Alice Exemple","slot":"09:00"}'
curl -X DELETE http://localhost:8766/api/bookings/IDENTIFIANT_RETOURNE
```

Les créneaux représentent une journée fictive, sans date ni fuseau horaire. Réponse 201 pour une création, 409 pour un créneau occupé, 400 pour une demande invalide, 404 pour une annulation inconnue. Réservations en mémoire : perdues à chaque arrêt du serveur.

## Automatisation CSV

```sh
python3 automation/clean_contacts.py automation/exemple.csv /tmp/contacts-propres.csv
```

Produit un CSV et `/tmp/contacts-propres.report.json`. Format UTF-8, en-têtes `nom,email` (ou point-virgule/tabulation). Les colonnes supplémentaires ne sont pas conservées. Déduplication par email, première ligne valide conservée ; validation de syntaxe simple, sans vérification de délivrabilité. Les valeurs qui pourraient être interprétées comme formules de tableur sont neutralisées. Les lignes invalides sont indiquées dans le rapport. Utiliser uniquement des données fictives dans la démo.

## Structure

- `web/` : portfolio et interfaces autonomes sans dépendance réseau.
- `server.py` : serveur local Python, API et stockage SQLite.
- `api-node/` : serveur Node.js indépendant et ses tests.
- `automation/` : script CSV autonome et jeu d’exemple.
- `tests/` : vérifications Python de bout en bout.

## Limites et adaptation pour un client

Ces templates sont des démonstrations locales : pas d’authentification, de gestion des droits, d’hébergement de production ni de sauvegarde automatisée. Ne pas exposer directement ces serveurs sur Internet. Pour une livraison client, prévoir selon le besoin : authentification, sauvegardes, hébergement HTTPS, protection des données, supervision, tests d’usage et adaptation graphique. Le simulateur artisan n’envoie aucun formulaire et ses prix sont fictifs. Mission Desk stocke ses données dans le navigateur courant ; l’export est manuel. Aucun paiement ni envoi d’email n’est effectué.

Ce dépôt ne contient pas l’application privée de facturation prévue ultérieurement, ni aucune donnée comptable ou personnelle réelle.

## Licence

MIT — voir `LICENSE`.
