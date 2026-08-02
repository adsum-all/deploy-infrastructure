"""Turn a client's file into the settings that make the platform theirs.

Opening an organisation used to mean editing source files: a name here, a colour
there, an address in a front-end component. Nobody could do it without a developer,
and nothing said when it was finished. This reads one document and produces exactly
what has to be written, so the answer to "is this client ready" is a command rather
than a reading of the code.

Two deliberate choices:

Refuse rather than approximate. A missing time zone, a colour that is not a hex, an
application address that is not plainly http: each of those produces a broken client
that looks configured. They are reported as errors, with the field named, instead of
being silently replaced by a default that belongs to somebody else.

Produce, do not apply. This module returns rows. Writing them to a database is the
caller's decision, made once, against a named target. A tool that both computes and
writes is a tool nobody dares run twice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The identifier names Cloudflare projects and a secrets folder, so it lives under
#: the intersection of what those two accept.
_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9-]{1,48}[a-z0-9]$")
#: An application identifier for the store: reversed domain, lower case, no dash.
_APP_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_COULEUR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_COURRIEL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Free mail domains. A sending provider cannot authenticate a domain it does not
#: control, so a message sent from one of these fails alignment and is refused or
#: filed as junk. This platform has already lost registrations that way, which is why
#: it is an error and not a remark.
_DOMAINES_LIBRES = frozenset({
    "gmail.com", "googlemail.com", "yahoo.fr", "yahoo.com", "hotmail.com",
    "hotmail.fr", "outlook.com", "outlook.fr", "live.fr", "live.com",
    "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "laposte.net", "icloud.com",
})

#: Which application address feeds which setting. Only these three are read by the
#: identity route; the others exist in the file for the operator, not for the code.
_ADRESSES_PUBLIEES = {
    "membre": "org_url_membre",
    "back_office": "org_url_back_office",
    "public": "org_url_public",
}

_FACETTES = ("singulier", "pluriel", "article")
#: The articles French uses before a common noun. Anything else is a typo that would
#: land mid-sentence in the interface.
_ARTICLES = ("le", "la", "les", "l'")


@dataclass
class Dossier:
    """One client, validated. `erreurs` is empty exactly when it can be opened."""

    identifiant: str
    brut: dict[str, Any]
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    @property
    def valide(self) -> bool:
        return not self.erreurs


def _texte(source: dict[str, Any], cle: str) -> str:
    valeur = source.get(cle)
    return valeur.strip() if isinstance(valeur, str) else ""


def _valider_organisation(org: dict[str, Any], erreurs: list[str]) -> None:
    for cle in ("nom", "nom_court", "marque", "ville", "fuseau"):
        if not _texte(org, cle):
            erreurs.append(f"organisation.{cle} est obligatoire")
    fuseau = _texte(org, "fuseau")
    if fuseau and "/" not in fuseau:
        erreurs.append(
            f"organisation.fuseau : « {fuseau} » n'est pas un identifiant IANA "
            "(attendu de la forme Europe/Paris ou Africa/Abidjan)",
        )
    for cle in ("site", "logo_url"):
        adresse = _texte(org, cle)
        if adresse and not adresse.startswith(("http://", "https://")):
            erreurs.append(f"organisation.{cle} doit commencer par http:// ou https://")


def _valider_couleurs(couleurs: dict[str, Any], erreurs: list[str]) -> None:
    for cle in ("principale", "sombre"):
        valeur = _texte(couleurs, cle)
        if not valeur:
            erreurs.append(f"couleurs.{cle} est obligatoire")
        elif not _COULEUR.match(valeur):
            erreurs.append(
                f"couleurs.{cle} : « {valeur} » n'est pas un hexadécimal "
                "(attendu #7a1f3d ou #abc)",
            )


def _valider_vocabulaire(vocabulaire: dict[str, Any], erreurs: list[str]) -> None:
    for terme, formes in vocabulaire.items():
        if terme.startswith("_"):
            continue
        if not isinstance(formes, dict):
            erreurs.append(f"vocabulaire.{terme} doit porter singulier, pluriel et article")
            continue
        for facette in _FACETTES:
            if not _texte(formes, facette):
                erreurs.append(f"vocabulaire.{terme}.{facette} est obligatoire")
        article = _texte(formes, "article")
        if article and article not in _ARTICLES:
            erreurs.append(
                f"vocabulaire.{terme}.article : « {article} » n'est pas un article "
                f"({', '.join(_ARTICLES)})",
            )


def _valider_applications(apps: dict[str, Any], erreurs: list[str], avertissements: list[str]) -> None:
    if not _texte(apps, "api"):
        erreurs.append("applications.api est obligatoire : sans elle aucune application ne parle au serveur")
    for cle, valeur in apps.items():
        if cle.startswith("_"):
            continue
        adresse = valeur.strip() if isinstance(valeur, str) else ""
        if adresse and not adresse.startswith(("http://", "https://")):
            erreurs.append(f"applications.{cle} doit commencer par http:// ou https://")
        elif adresse and " " in adresse:
            erreurs.append(f"applications.{cle} contient une espace")
    fermees = [c for c, v in apps.items()
               if not c.startswith("_") and isinstance(v, str) and not v.strip()]
    if fermees:
        avertissements.append(
            "applications non ouvertes pour ce client : " + ", ".join(sorted(fermees))
            + ". Aucune autre application n'y renverra.",
        )


def _valider_mobile(mobile: dict[str, Any], erreurs: list[str]) -> None:
    app_id = _texte(mobile, "app_id")
    if not app_id:
        erreurs.append("mobile.app_id est obligatoire")
    elif not _APP_ID.match(app_id):
        erreurs.append(
            f"mobile.app_id : « {app_id} » doit être un domaine inversé en minuscules "
            "(org.maparoisse.membres), sans tiret ni majuscule",
        )
    nom = _texte(mobile, "app_name")
    if not nom:
        erreurs.append("mobile.app_name est obligatoire")
    elif len(nom) > 30:
        erreurs.append("mobile.app_name dépasse 30 caractères et serait tronqué sous l'icône")
    code = mobile.get("version_code")
    if not isinstance(code, int) or isinstance(code, bool) or code < 1:
        erreurs.append("mobile.version_code doit être un entier positif")


def _valider_courriel(courriel: dict[str, Any], erreurs: list[str]) -> None:
    adresse = _texte(courriel, "expediteur")
    if not adresse:
        erreurs.append("courriel.expediteur est obligatoire")
        return
    if not _COURRIEL.match(adresse):
        erreurs.append(f"courriel.expediteur : « {adresse} » n'est pas une adresse")
        return
    domaine = adresse.rsplit("@", 1)[-1].lower()
    if domaine in _DOMAINES_LIBRES:
        erreurs.append(
            f"courriel.expediteur est sur {domaine}, un domaine de messagerie gratuite. "
            "Un fournisseur d'envoi ne peut pas l'authentifier : les messages seront "
            "refusés ou classés en indésirables. Utilisez une adresse sur un domaine "
            "que le client contrôle.",
        )


def charger(chemin: Path) -> Dossier:
    """Read and validate a client file. Never raises on content: it reports."""
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erreur:
        return Dossier(identifiant=chemin.stem, brut={}, erreurs=[f"JSON illisible : {erreur}"])
    if not isinstance(brut, dict):
        return Dossier(identifiant=chemin.stem, brut={}, erreurs=["le fichier doit contenir un objet"])

    erreurs: list[str] = []
    avertissements: list[str] = []

    identifiant = _texte(brut, "identifiant")
    if not identifiant:
        erreurs.append("identifiant est obligatoire")
    elif not _IDENTIFIANT.match(identifiant):
        erreurs.append(
            f"identifiant : « {identifiant} » doit être en minuscules, chiffres et "
            "tirets, commencer par une lettre et ne pas finir par un tiret",
        )
    elif identifiant != chemin.stem:
        avertissements.append(
            f"l'identifiant « {identifiant} » ne correspond pas au nom du fichier "
            f"« {chemin.stem} », ce qui rend le dossier difficile à retrouver",
        )

    _valider_organisation(brut.get("organisation") or {}, erreurs)
    _valider_couleurs(brut.get("couleurs") or {}, erreurs)
    _valider_vocabulaire(brut.get("vocabulaire") or {}, erreurs)
    _valider_applications(brut.get("applications") or {}, erreurs, avertissements)
    _valider_mobile(brut.get("mobile") or {}, erreurs)
    _valider_courriel(brut.get("courriel") or {}, erreurs)

    return Dossier(identifiant=identifiant or chemin.stem, brut=brut,
                   erreurs=erreurs, avertissements=avertissements)


def reglages(dossier: Dossier) -> dict[str, str]:
    """The integration_config rows that make the platform this client's.

    Only settings with a value: an empty string would overwrite a configured value
    with nothing, which is not what "not filled in" means.
    """
    if not dossier.valide:
        raise ValueError("dossier invalide : corrigez les erreurs avant de produire les réglages")
    org = dossier.brut.get("organisation") or {}
    couleurs = dossier.brut.get("couleurs") or {}
    apps = dossier.brut.get("applications") or {}
    courriel = dossier.brut.get("courriel") or {}

    valeurs = {
        "org_nom": _texte(org, "nom"),
        "org_nom_court": _texte(org, "nom_court"),
        "org_marque": _texte(org, "marque"),
        "org_ville": _texte(org, "ville"),
        "org_fuseau": _texte(org, "fuseau"),
        "org_site": _texte(org, "site"),
        "org_slogan": _texte(org, "slogan"),
        "org_logo_url": _texte(org, "logo_url"),
        "org_signature": _texte(org, "signature") or _texte(org, "nom"),
        "org_baseline": _texte(org, "baseline"),
        "org_couleur_principale": _texte(couleurs, "principale"),
        "org_couleur_sombre": _texte(couleurs, "sombre"),
        "email_from": _texte(courriel, "expediteur"),
        "email_from_name": _texte(courriel, "nom_expediteur") or _texte(org, "nom"),
        "email_provider": _texte(courriel, "fournisseur") or "brevo",
    }
    for application, cle in _ADRESSES_PUBLIEES.items():
        valeurs[cle] = _texte(apps, application)
    return {c: v for c, v in valeurs.items() if v}


def mots(dossier: Dossier) -> list[tuple[str, str, str, str]]:
    """The organisation_vocabulaire rows: (terme, singulier, pluriel, article)."""
    if not dossier.valide:
        raise ValueError("dossier invalide : corrigez les erreurs avant de produire le vocabulaire")
    sortie: list[tuple[str, str, str, str]] = []
    for terme, formes in (dossier.brut.get("vocabulaire") or {}).items():
        if terme.startswith("_") or not isinstance(formes, dict):
            continue
        sortie.append((
            terme, _texte(formes, "singulier"), _texte(formes, "pluriel"), _texte(formes, "article"),
        ))
    return sorted(sortie)


def identite_mobile(dossier: Dossier) -> dict[str, Any]:
    """The contents of the mobile application's marque.config.json for this client."""
    if not dossier.valide:
        raise ValueError("dossier invalide : corrigez les erreurs avant de produire l'identité mobile")
    org = dossier.brut.get("organisation") or {}
    couleurs = dossier.brut.get("couleurs") or {}
    apps = dossier.brut.get("applications") or {}
    mobile = dossier.brut.get("mobile") or {}
    return {
        "appId": _texte(mobile, "app_id"),
        "appName": _texte(mobile, "app_name"),
        "organisation": _texte(org, "nom"),
        "couleurPrincipale": _texte(couleurs, "principale"),
        "couleurFond": "#ffffff",
        "apiUrl": _texte(apps, "api"),
        "versionName": _texte(mobile, "version_name") or "1.0",
        "versionCode": mobile.get("version_code", 1),
    }
