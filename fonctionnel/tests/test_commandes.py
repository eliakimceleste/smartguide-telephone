import pytest

from aides import LIEUX, ident
from commandes import interprete, normalise


def test_normalise():
    assert normalise("  Où suis-je ? ") == "ou suis je"


@pytest.mark.parametrize("phrase, nom", [
    ("emmène-moi au marché", "Marché du quartier"),
    ("Guide-moi vers l'église.", "Église Saint-Michel"),
    ("je voudrais rentrer chez moi", "Maison"),
    ("je veux aller à la pharmacie les cocotiers", "Pharmacie Les Cocotiers"),
    ("aller aux Cocotiers", "Pharmacie Les Cocotiers"),
    ("chez mon ami", "Chez Koffi"),
])
def test_destination(phrase, nom):
    cmd = interprete(phrase, LIEUX)
    assert cmd.type == "aller" and cmd.lieu == ident(nom)


def test_type_de_lieu_donne_tous_les_candidats():
    cmd = interprete("je veux aller à la pharmacie", LIEUX)
    assert set(cmd.candidats) == {ident("Pharmacie du Carrefour"), ident("Pharmacie Les Cocotiers")}


def test_erreur_de_transcription():
    cmd = interprete("aller à la farmacie", LIEUX)
    assert cmd.type == "aller" and ident("Pharmacie Les Cocotiers") in cmd.candidats


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
