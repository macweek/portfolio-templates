# Studio Applications — cinq outils métier locaux

Une suite de cinq applications partageant une administration et une base SQLite. Il s’agit d’une version locale fonctionnelle : les données sont réellement enregistrées, les actions sont contrôlées côté serveur, et les écrans permettent de parcourir les usages de bout en bout.

## Démarrer

Python 3.9 ou supérieur, sans bibliothèque à installer :

```sh
python3 server.py
```

Ouvrir **http://localhost:8765**, puis **Administration**. Créer soi-même le compte propriétaire avec son email et un mot de passe de 12 caractères minimum. Les mots de passe sont hachés avec PBKDF2-HMAC-SHA256 (600 000 itérations, sel aléatoire). La session dure 12 heures et utilise un cookie HttpOnly / SameSite=Strict. Le service est limité à la machine locale. Arrêt : Ctrl+C.

Aucun identifiant prédéfini n’est fourni pour l’installation. La base commence vide ; le site dispose d’un contenu initial modifiable. Le bouton « Créer un exemple » du gestionnaire de commandes ajoute une commande fictive, seulement sur demande.

## 1. Site et demandes clients

- Vue visiteur : présentation, prestations, estimation indicative et demande de contact.
- Administration : modifier le nom, le titre, le texte, la couleur et les prestations existantes.
- Les demandes sont enregistrées dans une boîte de réception et peuvent être marquées traitées ou archivées.
- Les demandes ne déclenchent pas d’email automatique. Le lien email permet d’utiliser sa messagerie.

Parcours : modifier un titre → enregistrer → ouvrir le site → envoyer une demande → retrouver la demande dans l’administration.

## 2. Commandes, règlements et livraison

- Commandes persistantes : client, adresse, objet, lignes de produits ou prestations, quantités, prix, remise et TVA.
- Les montants sont calculés en centimes côté serveur, avec un arrondi au centime.
- Avancement de commande distinct du statut de livraison et de paiement.
- Règlements : acomptes, paiements partiels et soldes, avec moyen de paiement, date et référence. Le solde est calculé depuis les écritures.
- Deux paiements simultanés ne peuvent pas dépasser le solde : les écritures sont sérialisées en transaction.
- Livraison : non préparée, en préparation, prête, expédiée, livrée ; transporteur et référence facultatifs.
- Émission de facture : numéro annuel unique, copie figée des lignes et des coordonnées à l’émission, consultation et impression / sauvegarde PDF depuis le navigateur.
- Les lignes d’une commande facturée ne sont plus modifiables. Les paiements reçus et la livraison restent accessibles.
- Export des commandes en JSON.

Les règlements sont des paiements déjà reçus et enregistrés manuellement : cette application ne débite pas de carte bancaire. Avant une utilisation commerciale des factures, renseigner les mentions adaptées à son entreprise et faire valider le document. Cette version ne traite pas les avoirs, remboursements, corrections d’écritures de paiement, paiements en ligne ni la transmission de factures électroniques. Elle ne remplace pas un logiciel comptable certifié ou une plateforme de facturation agréée.

## 3. Inventaire et mouvements

- Créer et modifier une référence : nom, SKU unique, seuil d’alerte et valeur unitaire.
- Entrées / sorties avec motif obligatoire et historique horodaté.
- Transactions SQLite pour empêcher un stock négatif, même lors de sorties concurrentes.
- Alertes sous le seuil, valeur totale, recherche et export CSV.
- Archivage d’une référence à stock nul, avec conservation de son historique.
- L’écran et son export de mouvements affichent les 200 derniers mouvements ; l’export global inclut tout l’historique.

## 4. Nettoyage CSV

- Import UTF-8 ou collage direct, aperçu avant / après et exemple à charger.
- Colonnes requises : `nom` et `email`, en-têtes insensibles à la casse et espaces externes nettoyés.
- Virgule, point-virgule ou tabulation. Maximum 1 Mo.
- Normalisation des emails, déduplication par email (première ligne valide conservée), contrôle de syntaxe et rapport des lignes rejetées.
- Neutralisation des formules de tableur dans les cellules exportées.
- Téléchargement du CSV nettoyé et du rapport JSON.
- Historique des traitements : seul le nom du fichier et les compteurs sont enregistrés ; le contenu des contacts ne l’est pas.

Le fichier source n’est jamais modifié. Seules les colonnes nom et email sont conservées ; la validité réelle des boîtes email n’est pas vérifiée.

Utilisation autonome, sans serveur :

```sh
python3 automation/clean_contacts.py automation/exemple.csv /tmp/contacts-propres.csv
```

## 5. Réservations et planning

- Vue visiteur : choix de prestation, date, créneau et confirmation.
- Créneaux d’une heure, heure de Paris, dans les douze prochains mois.
- Contrôle transactionnel empêchant les doubles réservations et les chevauchements.
- Confirmation avec lien privé d’annulation. Conserver ce lien : aucun email n’est envoyé.
- Planning administrateur : recherche par date, statuts confirmé / réalisé / annulé et export JSON.
- Disponibilités configurables : créneaux et jours de fermeture hebdomadaires. Les rendez-vous existants sont conservés.
- Les informations sont persistantes après redémarrage.

Cette version gère un seul agenda et des rendez-vous d’une heure. Elle ne propose pas de synchronisation calendrier, de rappels email / SMS ou d’encaissement.

## Données et sauvegarde

Base : `data/applications.sqlite3`, exclue de Git, permissions du fichier limitées au propriétaire. Le stockage n’est pas chiffré par l’application : protéger l’ordinateur et ses sauvegardes. Pour changer le chemin : variable `DEMO_DB`.

Pour une sauvegarde restaurable : arrêter le serveur puis copier le fichier SQLite. Pour restaurer : arrêter le serveur et replacer la copie à ce même chemin. L’export JSON de l’administration est consultable et contient les données métier, sans mots de passe ni sessions. Il n’existe pas d’import JSON.

L’ancienne base `data/demo.sqlite3`, si présente, est conservée mais n’est pas utilisée ni migrée : elle appartenait à la première démonstration.

## Vérification

```sh
python3 -m unittest discover -s tests -v
```

Les tests utilisent un serveur et une base temporaires, sans toucher aux données locales. Ils vérifient notamment : accès privé, rejet des requêtes intersites, calculs de remise / TVA, paiements concurrents, gel de facture, livraison, stock concurrent, annulation de réservation et traitement CSV.

## Structure et API

- `server.py` : serveur HTTP local, authentification, API et transactions.
- `web/` : interfaces HTML / CSS / JavaScript sans dépendances externes.
- `automation/` : nettoyage CSV utilisable séparément.
- `tests/` : tests d’intégration du serveur.
- `api-node/` : exemple technique autonome de la première version, API Node.js de réservation en mémoire. Il n’est pas utilisé par la nouvelle suite ; le planning persistant utilise l’API Python.

Routes publiques : `/api/session`, `/api/site` (lecture), `/api/contact`, `/api/slots`, `/api/reservations` (création), `/api/reservations/cancel`. Routes privées : commandes, paiements, factures, inventaire, CSV, planning et paramètres. Création de compte unique via `/api/setup`, connexion `/api/login`, déconnexion `/api/logout`.

## Limites de livraison à un client

Les fonctionnalités décrites sont opérationnelles pour une installation locale mono-entreprise. Une mise à disposition sur Internet nécessite un serveur de production, HTTPS, gestion des secrets, sauvegardes automatisées, protection et supervision adaptées, ainsi qu’une validation des exigences du client et des documents de facturation. Le serveur inclus n’est pas un serveur de production. Il n’y a ni gestion multi-utilisateurs, ni réinitialisation de mot de passe par email, ni intégration bancaire. Ne pas exposer ce serveur local directement sur Internet.

La comptabilité privée et la préparation des déclarations fiscales restent un projet distinct. La suite ne réalise aucune déclaration administrative.

Licence MIT : voir LICENSE.
