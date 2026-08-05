"""Check a client's file, and show exactly what opening them would change.

Run without --appliquer it writes nothing: it validates, then prints the settings,
the vocabulary and the mobile identity that would be produced. That report is what an
operator reads before deciding, and what they attach to the ticket afterwards.

With --appliquer it writes those rows into the database named by ADSUM_DATABASE_URL.
The target is never inferred and never defaulted: opening the wrong client's settings
into the wrong database is not an error anybody notices quickly.

    python scripts/preparer_client.py clients/paroisse-saint-pierre.json
    python scripts/preparer_client.py clients/paroisse-saint-pierre.json --appliquer

Exit code 0 when the file is valid, 1 when it is not, so a pipeline can gate on it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import charger, identite_mobile, mots, reglages  # noqa: E402


def _rapporter(dossier) -> None:
    print(f"Client : {dossier.identifiant}")
    if dossier.avertissements:
        print("\nÀ vérifier :")
        for a in dossier.avertissements:
            print(f"   - {a}")
    if dossier.erreurs:
        print("\nCe dossier ne peut pas être ouvert :")
        for e in dossier.erreurs:
            print(f"   - {e}")
        return

    valeurs = reglages(dossier)
    print(f"\nRéglages à écrire ({len(valeurs)}) :")
    for cle in sorted(valeurs):
        print(f"   {cle:26} {valeurs[cle]}")

    vocabulaire = mots(dossier)
    print(f"\nMots de l'organisation ({len(vocabulaire)}) :")
    for terme, singulier, pluriel, article in vocabulaire:
        print(f"   {terme:14} {article} {singulier} / {pluriel}")

    print("\nIdentité de l'application mobile (marque.config.json) :")
    for cle, valeur in identite_mobile(dossier).items():
        print(f"   {cle:18} {valeur}")


def _appliquer(dossier) -> None:
    """Write the rows. Imported here so a dry run needs no database driver."""
    url = (os.environ.get("ADSUM_DATABASE_URL") or "").strip()
    if not url:
        print("\nADSUM_DATABASE_URL n'est pas défini. Rien n'a été écrit : la base "
              "cible doit être nommée explicitement.", file=sys.stderr)
        raise SystemExit(2)

    import psycopg

    valeurs = reglages(dossier)
    vocabulaire = mots(dossier)
    # One transaction: a client half configured shows its own name in one screen and
    # somebody else's in the next, which is worse than not being configured at all.
    with psycopg.connect(url) as connexion, connexion.cursor() as curseur:
        for cle, valeur in valeurs.items():
            curseur.execute(
                "INSERT INTO integration_config (cle, valeur, maj_le) VALUES (%s, %s, now()) "
                "ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur, maj_le = now()",
                (cle, valeur),
            )
        for terme, singulier, pluriel, article in vocabulaire:
            curseur.execute(
                "INSERT INTO organisation_vocabulaire (terme, singulier, pluriel, article) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (terme) DO UPDATE SET "
                "singulier = EXCLUDED.singulier, pluriel = EXCLUDED.pluriel, "
                "article = EXCLUDED.article",
                (terme, singulier, pluriel, article),
            )
    print(f"\nÉcrit : {len(valeurs)} réglages, {len(vocabulaire)} mots.")


def main() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("dossier", type=Path, help="le fichier du client, sous clients/")
    analyseur.add_argument("--appliquer", action="store_true",
                           help="écrire dans la base désignée par ADSUM_DATABASE_URL")
    analyseur.add_argument("--mobile", type=Path, default=None,
                           help="écrire aussi le marque.config.json de l'application mobile")
    arguments = analyseur.parse_args()

    if not arguments.dossier.exists():
        print(f"introuvable : {arguments.dossier}", file=sys.stderr)
        raise SystemExit(2)

    dossier = charger(arguments.dossier)
    _rapporter(dossier)
    if not dossier.valide:
        raise SystemExit(1)

    if arguments.mobile:
        arguments.mobile.write_text(
            json.dumps(identite_mobile(dossier), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nIdentité mobile écrite dans {arguments.mobile}")

    if arguments.appliquer:
        _appliquer(dossier)
    else:
        print("\nRien n'a été écrit. Ajoutez --appliquer pour enregistrer ces valeurs.")


if __name__ == "__main__":
    main()
