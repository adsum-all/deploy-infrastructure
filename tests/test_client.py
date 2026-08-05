"""A client's file must be refused before it produces a half-working organisation.

The failures that matter are the quiet ones: a colour that is not a colour, a sending
address on a free-mail domain, an application identifier the store will reject, a time
zone that is not one. Each of those produces a client that looks configured and is
not, and each is found weeks later by somebody who cannot sign in, cannot receive a
message, or reads times that are three hours out.

So these tests are mostly about what the loader REFUSES, and about the fact that it
names the field rather than failing vaguely.

    python -m pytest deployment/infrastructure/tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from client import charger, identite_mobile, mots, reglages  # noqa: E402

_EXEMPLE = Path(__file__).resolve().parents[1] / "clients" / "exemple.json"


def _dossier(tmp_path: Path, **remplacements) -> Path:
    """The shipped example, with the given sections replaced. Written under tmp_path."""
    brut = json.loads(_EXEMPLE.read_text(encoding="utf-8"))
    for chemin, valeur in remplacements.items():
        section, _, champ = chemin.partition(".")
        if champ:
            brut.setdefault(section, {})[champ] = valeur
        else:
            brut[section] = valeur
    cible = tmp_path / f"{brut.get('identifiant', 'client')}.json"
    cible.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")
    return cible


def test_the_shipped_example_is_a_client_that_could_actually_be_opened():
    """A template that does not validate teaches the operator the wrong shape."""
    dossier = charger(_EXEMPLE)
    assert dossier.valide, dossier.erreurs


def test_the_example_produces_settings_that_carry_none_of_this_organisation(tmp_path):
    dossier = charger(_dossier(tmp_path))
    valeurs = reglages(dossier)
    assert valeurs["org_nom"] == "Paroisse Saint-Pierre"
    assert valeurs["org_couleur_principale"] == "#7a1f3d"
    rendu = json.dumps(valeurs, ensure_ascii=False)
    for trace in ("Sacerdoce", "ADSUM", "Abidjan", "2a4fad"):
        assert trace not in rendu


@pytest.mark.parametrize("adresse", [
    "paroisse@gmail.com", "contact@yahoo.fr", "info@Hotmail.com", "x@orange.fr",
])
def test_a_sender_on_a_free_mail_domain_is_refused_with_the_reason(tmp_path, adresse):
    """This exact configuration has already cost this platform real registrations."""
    dossier = charger(_dossier(tmp_path, **{"courriel.expediteur": adresse}))
    assert not dossier.valide
    faute = " ".join(dossier.erreurs)
    assert "courriel.expediteur" in faute
    assert "authentifier" in faute


def test_a_sender_on_the_client_own_domain_is_accepted(tmp_path):
    dossier = charger(_dossier(tmp_path, **{"courriel.expediteur": "envois@saint-pierre.example"}))
    assert dossier.valide, dossier.erreurs


@pytest.mark.parametrize("couleur", ["7a1f3d", "rouge", "#12345", "", "#7a1f3d;x"])
def test_a_colour_that_is_not_a_hex_is_refused(tmp_path, couleur):
    dossier = charger(_dossier(tmp_path, **{"couleurs.principale": couleur}))
    assert not dossier.valide
    assert any("couleurs.principale" in e for e in dossier.erreurs)


@pytest.mark.parametrize("couleur", ["#abc", "#7A1F3D"])
def test_a_real_hex_colour_is_accepted_in_both_lengths(tmp_path, couleur):
    assert charger(_dossier(tmp_path, **{"couleurs.principale": couleur})).valide


@pytest.mark.parametrize("app_id", [
    "org.ma-paroisse.membres",   # a dash is refused by the store
    "Org.Paroisse.Membres",      # upper case likewise
    "paroisse",                  # no reversed domain
    "",
])
def test_an_application_identifier_the_store_would_reject_is_refused(tmp_path, app_id):
    dossier = charger(_dossier(tmp_path, **{"mobile.app_id": app_id}))
    assert not dossier.valide
    assert any("mobile.app_id" in e for e in dossier.erreurs)


def test_a_time_zone_that_is_not_one_is_refused(tmp_path):
    """Times are shown in this zone. Wrong, every activity is at the wrong hour."""
    dossier = charger(_dossier(tmp_path, **{"organisation.fuseau": "GMT+1"}))
    assert not dossier.valide
    assert any("fuseau" in e for e in dossier.erreurs)


def test_a_missing_api_address_is_refused_because_nothing_would_work(tmp_path):
    dossier = charger(_dossier(tmp_path, **{"applications.api": ""}))
    assert not dossier.valide
    assert any("applications.api" in e for e in dossier.erreurs)


def test_an_unopened_application_is_a_remark_not_an_error(tmp_path):
    """Not every client buys every application; that is a choice, not a mistake."""
    dossier = charger(_dossier(tmp_path, **{"applications.public": ""}))
    assert dossier.valide, dossier.erreurs
    assert any("non ouvertes" in a for a in dossier.avertissements)
    # And the setting is absent rather than empty: an empty string written over a
    # configured address would erase it.
    assert "org_url_public" not in reglages(dossier)


@pytest.mark.parametrize("identifiant", ["Paroisse", "1paroisse", "paroisse-", "pa", ""])
def test_an_identifier_that_would_break_a_project_name_is_refused(tmp_path, identifiant):
    dossier = charger(_dossier(tmp_path, identifiant=identifiant))
    assert not dossier.valide
    assert any("identifiant" in e for e in dossier.erreurs)


def test_an_article_that_is_not_one_is_refused(tmp_path):
    """The article lands mid-sentence in the interface; a typo is visible to members."""
    dossier = charger(_dossier(tmp_path, vocabulaire={
        "tribu": {"singulier": "secteur", "pluriel": "secteurs", "article": "du"},
    }))
    assert not dossier.valide
    assert any("article" in e for e in dossier.erreurs)


def test_the_vocabulary_reading_key_is_kept_and_only_the_word_changes(tmp_path):
    """Screens look a word up by "tribu". Renaming the key would blank the label."""
    dossier = charger(_dossier(tmp_path))
    termes = dict((t, (s, p, a)) for t, s, p, a in mots(dossier))
    assert termes["tribu"] == ("secteur", "secteurs", "le")


def test_an_unreadable_file_is_reported_rather_than_raised(tmp_path):
    cassé = tmp_path / "cassé.json"
    cassé.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    dossier = charger(cassé)
    assert not dossier.valide
    assert any("JSON" in e for e in dossier.erreurs)


def test_producing_settings_from_an_invalid_file_is_refused(tmp_path):
    """Better a loud stop than a database holding half a client."""
    dossier = charger(_dossier(tmp_path, **{"couleurs.principale": "rouge"}))
    for produire in (reglages, mots, identite_mobile):
        with pytest.raises(ValueError):
            produire(dossier)


def test_the_mobile_identity_targets_the_client_own_server(tmp_path):
    """Without this, the application installed on their members' phones talks to
    somebody else's server."""
    identite = identite_mobile(charger(_dossier(tmp_path)))
    assert identite["apiUrl"] == "https://paroisse-saint-pierre-api.vercel.app"
    assert identite["appId"] == "org.saintpierre.membres"
    assert "adsum-api.vercel.app" not in json.dumps(identite)
