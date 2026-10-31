import os

import geo
from guidage import Guide, metres, mot_direction
from osm import plan_depuis_osm
from position import Simulateur

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = plan_depuis_osm(os.path.join(ICI, "exemple", "carte_exemple.json"),
                       os.path.join(ICI, "exemple", "destinations_exemple.json"))


def test_geo():
    a = (6.417, 2.342)
    b = geo.deplace(a, 90, 100)
    assert abs(geo.distance(a, b) - 100) < 0.5
    assert abs(geo.cap(a, b) - 90) < 0.5
    assert geo.angle_relatif(10, 350) == 20


def test_mots():
    assert mot_direction(0) == "tout droit"
    assert mot_direction(90) == "à droite"
    assert mot_direction(-40) == "légèrement à gauche"
    assert mot_direction(170) == "demi-tour"
    assert metres(43) == "45 mètres" and metres(7.2) == "7 mètres"


def test_plus_court_chemin():
    it = PLAN.itineraire(PLAN.point("maison"), "pharmacie")
    assert it.destination == "Pharmacie"
    assert 180 < it.longueur() < 215   # 5 + 140 + 52 m environ


def _marche(depart, arrivee, **options):
    it = PLAN.itineraire(PLAN.point(depart), arrivee)
    guide = Guide(it)
    sim = Simulateur(it.points, acceleration=0, **options)
    dits = []
    for n, m in enumerate(sim):
        etat = guide.mise_a_jour(m.position, m.cap, m.instant)
        dits += etat.messages
        if etat.recalcul:
            it = PLAN.itineraire(m.position, arrivee)
            guide = Guide(it)
            sim.nouveau_trajet(it.points)
        if etat.arrive or n > 600:
            break
    return dits


def test_arrivee_et_virage():
    dits = _marche("maison", "pharmacie")
    assert dits[-1] == "Destination atteinte : Pharmacie."
    assert "Tournez à droite maintenant." in dits
    assert any(d.startswith("Dans ") and "tournez à droite" in d for d in dits)


def test_recalcul_apres_erreur():
    dits = _marche("maison", "eglise", ecarts={n: 90.0 for n in range(20, 40)})
    assert "Vous avez quitté le trajet, je recalcule." in dits
    assert dits[-1] == "Destination atteinte : Église."
