# infrastructure

Part of the ADSUM platform (membership, QR check-in and attendance).
Subgroup: `deployment`.

## Role

Infrastructure as code (Supabase per environment, S3 buckets, DNS, secrets), and
the procedure for opening a new client organisation.

## Ouvrir une organisation

La plateforme est vendue à des associations, paroisses, groupes de prière et
églises. Rien de ce qu'une organisation voit à l'écran n'est écrit dans le code :
son nom, sa marque, ses couleurs, ses mots et les adresses de ses applications sont
des réglages. Ouvrir un client consiste donc à produire un dossier, puis à écrire ce
qu'il décrit.

### 1. Le dossier du client

Copiez `clients/exemple.json` sous `clients/<identifiant>.json` et remplissez-le.
C'est le seul document à produire. Chaque champ y est commenté par un champ voisin
préfixé d'un souligné.

Trois pièges que le validateur refuse explicitement, parce qu'ils produisent un
client qui a l'air configuré et ne l'est pas :

| Champ | Refus | Pourquoi |
|---|---|---|
| `courriel.expediteur` | adresse sur gmail.com, yahoo.fr, orange.fr | Un fournisseur d'envoi ne peut pas authentifier un domaine qu'il ne contrôle pas. Les messages sont refusés ou classés en indésirables. Cette plateforme a déjà perdu des inscriptions ainsi. |
| `organisation.fuseau` | tout ce qui n'est pas un identifiant IANA | Détermine l'heure de chaque activité, relance et récapitulatif. Faux, tout se produit à la mauvaise heure. |
| `mobile.app_id` | tiret, majuscule, absence de domaine inversé | Google Play refuse l'identifiant, et il ne peut plus changer après publication. |

### 2. Vérifier, sans rien écrire

```bash
python scripts/preparer_client.py clients/<identifiant>.json
```

Le script valide le dossier et affiche exactement ce qui serait écrit : les
réglages, les mots de l'organisation et l'identité de l'application mobile. Il
n'écrit rien. Code de sortie 0 si le dossier est ouvrable, 1 sinon, de sorte qu'un
pipeline peut s'y arrêter.

### 3. Écrire les réglages

```bash
ADSUM_DATABASE_URL="postgresql://..." \
  python scripts/preparer_client.py clients/<identifiant>.json --appliquer
```

La base cible est nommée explicitement, jamais déduite : écrire les réglages d'un
client dans la base d'un autre ne se remarque pas vite. Réglages et vocabulaire
partent dans une seule transaction, pour qu'un client à moitié configuré ne montre
pas son nom sur un écran et celui d'un autre sur le suivant.

### 4. L'application mobile

```bash
python scripts/preparer_client.py clients/<identifiant>.json \
  --mobile ../../applications/adsum-mobile/marque.config.json
cd ../../applications/adsum-mobile
npm run prepare:web && npx cap sync android && node scripts/appliquer-marque.mjs
```

`appliquer-marque.mjs` reporte l'identité dans le projet Android (paquet, nom
affiché, version, couleurs). Sans lui, l'application publiée porterait le nom et le
paquet d'une autre organisation.

### 5. Les fronts

Chaque front est construit avec `VITE_API_URL` pointant sur l'API du client, puis
déployé sur son propre projet Cloudflare Pages. Le reste de l'identité est lu à
l'exécution sur la route publique `/api/v1/marque` : changer une couleur ou un nom
ne demande donc aucune reconstruction.

### 6. Le retour de livraison des courriels

Renseignez `email_webhook_secret`, relevez l'adresse de rappel dans le back office
(rubrique Intégrations) et collez-la chez le fournisseur, section Transactionnel
puis Webhooks. Sans cela la plateforme ignore ce que deviennent ses messages : elle
annonce « un code a été envoyé » alors que la boîte du destinataire les refuse, ce
qui a déjà bloqué une connexion pendant deux jours sans que rien ne le signale.

### Tests

```bash
python -m pytest tests -q
```

Ils couvrent surtout les refus du validateur : ce sont eux qui empêchent d'ouvrir un
client cassé, et ils comptent davantage que le chemin nominal.

## Stack

Terraform pour le provisionnement cloud. Python pour l'ouverture des clients.

## Conventions

- Branches: work on `feature/*` or `fix/*` from `develop`, then a merge request.
  Merge order `feature/* -> develop -> main`. Never push to `main`.
- Constitution (zero tolerance): no mock data, no file over 500 lines,
  no em-dash (U+2014 / U+2013), no secret in clear. CI enforces these.
- Commit messages in English, Conventional Commits.

## CI

Pipelines are defined in `.gitlab-ci.yml`, which includes the shared templates
from `sr-media-ai/adsum/deployment/ci-templates`.
