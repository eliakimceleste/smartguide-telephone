import json
import os

import pytest

from commandes import interprete, normalise

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIEUX = json.load(open(os.path.join(ICI, "exemple", "destinations_exemple.json"), encoding="utf-8"))["destinations"]


def test_normalise():
    assert normalise("  Où suis-je ? ") == "ou suis je"


@pytest.mark.parametrize("phrase, lieu", [
    ("Je veux aller à la pharmacie", "pharmacie"),
    ("emmène-moi au marché", "marche"),
    ("Guide-moi vers l'église.", "eglise"),
    ("la boutique", "boutique"),
    ("je voudrais rentrer chez moi", "maison"),
    ("aller à la farmacie", "pharmacie"),      # erreur de transcription
])
def test_destination(phrase, lieu):
    cmd = interprete(phrase, LIEUX)
    assert cmd.type == "aller" and cmd.lieu == lieu


def test_destination_inconnue():
    cmd = interprete("je veux aller à l'aéroport", LIEUX)
    assert cmd.type == "aller" and cmd.lieu is None


@pytest.mark.parametrize("phrase, type_", [
    ("Où suis-je ?", "ou_suis_je"),
    ("stop", "arreter"),
    ("Répète s'il te plaît", "repeter"),
    ("quelles destinations ?", "destinations"),
    ("oui", "oui"),
    ("non", "non"),
    ("il fait beau", "inconnu"),
])
def test_commandes(phrase, type_):
    assert interprete(phrase, LIEUX).type == type_
