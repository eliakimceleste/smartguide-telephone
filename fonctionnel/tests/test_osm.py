from aides import LIEUX, PLAN
from osm import categorie, charge_categories


def test_lieux_tires_de_la_carte():
    noms = {l["nom"] for l in LIEUX.values()}
    assert {"Maison", "Pharmacie du Carrefour", "Pharmacie Les Cocotiers", "Église Saint-Michel",
            "Marché du quartier", "Boutique Chez Awa", "Chez Koffi"} <= noms
    assert "Kiosque sans type" not in noms          # lieu sans type connu : ignoré
    assert PLAN.ignores == []


def test_categories():
    c = charge_categories()["categories"]
    assert categorie({"amenity": "place_of_worship", "religion": "muslim"}, c) == "mosquée"
    assert categorie({"amenity": "place_of_worship"}, c) == "lieu de culte"
    assert categorie({"shop": "bakery"}, c) == "boulangerie"
    assert categorie({"shop": "mobile_phone"}, c) == "boutique"
    assert categorie({"building": "yes"}, c) is None
