import os

from osm import plan_depuis_osm

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTE = os.path.join(ICI, "exemple", "carte_exemple.json")
MES_LIEUX = os.path.join(ICI, "exemple", "mes_lieux_exemple.json")
PLAN = plan_depuis_osm(CARTE, MES_LIEUX)
LIEUX = {i: PLAN.lieux[i] for i in PLAN.destinations()}


def ident(nom):
    """Identifiant d'un lieu à partir de son nom affiché."""
    return next(i for i, l in LIEUX.items() if l["nom"] == nom)
