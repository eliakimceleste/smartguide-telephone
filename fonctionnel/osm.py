"""Carte OpenStreetMap : téléchargement (une fois, avec Internet) et
transformation en plan pour le calcul d'itinéraire (sans Internet).

La carte contient les rues ET les lieux nommés de la zone (pharmacies,
églises, marchés…) : ils deviennent les destinations, sans rien saisir.
Le centre donné au téléchargement devient la destination « Maison ».

Usage, sur un PC connecté :
    python osm.py --centre 6.4170,2.3420 --rayon 1000 --sortie carte_zone.json
"""
import argparse
import json
import os
import unicodedata

import geo
from itineraire import Plan

OVERPASS = "https://overpass-api.de/api/interpreter"
ICI = os.path.dirname(os.path.abspath(__file__))

# Rues où l'on peut marcher (sans autoroutes ni voies interdites aux piétons),
# leurs points, et les lieux qui ont un nom.
REQUETE = """
[out:json][timeout:120];
way["highway"]["highway"!~"^(motorway|motorway_link|trunk|trunk_link|construction|proposed)$"]
   ["foot"!~"^(no|private)$"]["access"!~"^(no|private)$"]({b})->.voies;
node(w.voies)->.points;
(
  nwr["name"]["amenity"]({b});
  nwr["name"]["shop"]({b});
  nwr["name"]["tourism"]({b});
  nwr["name"]["leisure"]({b});
  nwr["name"]["office"]({b});
  nwr["name"]["healthcare"]({b});
)->.lieux;
.voies out body;
.points out skel qt;
.lieux out center tags;
"""


def boite(centre, rayon):
    """Rectangle (sud, ouest, nord, est) autour d'un centre, rayon en mètres."""
    sud, _ = geo.deplace(centre, 180, rayon)
    nord, _ = geo.deplace(centre, 0, rayon)
    _, ouest = geo.deplace(centre, 270, rayon)
    _, est = geo.deplace(centre, 90, rayon)
    return sud, ouest, nord, est


def telecharge(centre, rayon, sortie):
    import requests  # seulement pour le téléchargement

    b = ",".join(str(x) for x in boite(centre, rayon))
    r = requests.post(OVERPASS, data={"data": REQUETE.format(b=b)}, timeout=180,
                      headers={"User-Agent": "SmartGuide (projet de memoire)"})
    r.raise_for_status()
    donnees = r.json()
    donnees["centre"] = list(centre)  # devient la destination « Maison »
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False)
    elements = donnees["elements"]
    voies = sum(1 for el in elements if el["type"] == "way" and "highway" in el.get("tags", {}))
    lieux = len(lieux_nommes(elements, charge_categories()))
    return voies, lieux


def charge_categories(fichier=os.path.join(ICI, "categories_osm.json")):
    with open(fichier, encoding="utf-8") as f:
        return json.load(f)


def _sans_accents(texte):
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def categorie(tags, categories):
    """Mot du type de lieu (« pharmacie », « église »…), ou None."""
    for regle, mot in categories.items():
        conditions = regle.split("+")
        if all(("=" in c and tags.get(c.split("=")[0]) == c.split("=")[1])
               or ("=" not in c and c in tags) for c in conditions):
            return mot
    return None


def lieux_nommes(elements, config):
    """Destinations tirées des lieux nommés de la carte."""
    lieux = {}
    for el in elements:
        tags = el.get("tags", {})
        if "name" not in tags or "highway" in tags:
            continue
        lat, lon = (el["lat"], el["lon"]) if "lat" in el else \
            (el.get("center", {}).get("lat"), el.get("center", {}).get("lon"))
        if lat is None:
            continue
        mot = categorie(tags, config["categories"])
        if mot is None:
            continue
        alias = [mot]
        # « Pharmacie Les Cocotiers » se dit aussi sans le mot « pharmacie ».
        if _sans_accents(tags["name"]).startswith(_sans_accents(mot) + " "):
            alias.append(tags["name"][len(mot) + 1:])
        lieux[f"osm_{el['type']}{el['id']}"] = {"nom": tags["name"], "categorie": mot,
                                                 "alias": alias, "lat": lat, "lon": lon}
    return lieux


def plan_depuis_osm(fichier_carte, fichier_destinations=None, liaison_max=80.0):
    """Construit le Plan : les rues de la carte, plus les destinations.

    Destinations = les lieux nommés de la carte, « Maison » au centre du
    téléchargement, et, si on en donne un, les lieux du fichier personnel.
    Chaque destination est reliée au point de rue le plus proche ; celles à
    plus de `liaison_max` mètres d'une rue sont ignorées (et comptées).
    """
    with open(fichier_carte, encoding="utf-8") as f:
        donnees = json.load(f)
    elements = donnees["elements"]
    config = charge_categories()

    destinations = lieux_nommes(elements, config)
    if "centre" in donnees:
        lat, lon = donnees["centre"]
        destinations["maison"] = {**config["maison"], "categorie": "maison", "lat": lat, "lon": lon}
    if fichier_destinations:
        with open(fichier_destinations, encoding="utf-8") as f:
            destinations.update(json.load(f)["destinations"])

    noeuds = {el["id"]: (el["lat"], el["lon"]) for el in elements if el["type"] == "node" and "lat" in el}
    lieux, chemins = {}, []
    for el in elements:
        if el["type"] != "way" or "highway" not in el.get("tags", {}):
            continue
        ids = [i for i in el["nodes"] if i in noeuds]
        for a, b in zip(ids, ids[1:]):
            for i in (a, b):
                ident = f"osm{i}"
                if ident not in lieux:
                    lat, lon = noeuds[i]
                    lieux[ident] = {"nom": el["tags"].get("name", ""),
                                    "lat": lat, "lon": lon, "destination": False}
            chemins.append((f"osm{a}", f"osm{b}"))
    if not lieux:
        raise ValueError("La carte ne contient aucune rue praticable à pied.")

    voies = list(lieux)
    ignores = []
    for ident, dest in destinations.items():
        point = (dest["lat"], dest["lon"])
        proche = min(voies, key=lambda v: geo.distance(point, (lieux[v]["lat"], lieux[v]["lon"])))
        if geo.distance(point, (lieux[proche]["lat"], lieux[proche]["lon"])) > liaison_max:
            ignores.append(dest["nom"])
            continue
        lieux[ident] = {"nom": dest["nom"], "lat": dest["lat"], "lon": dest["lon"],
                        "alias": dest.get("alias", []), "categorie": dest.get("categorie"),
                        "destination": True}
        chemins.append((ident, proche))
    plan = Plan(lieux, chemins, titre=fichier_carte)
    plan.ignores = ignores
    return plan


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Télécharge la carte OpenStreetMap (rues et lieux) autour d'un point.")
    p.add_argument("--centre", required=True,
                   help="latitude,longitude de la maison (centre de la zone), ex. 6.4170,2.3420")
    p.add_argument("--rayon", type=float, default=1000, help="rayon en mètres (défaut 1000)")
    p.add_argument("--sortie", default="carte_zone.json")
    a = p.parse_args()
    centre = tuple(float(x) for x in a.centre.split(","))
    voies, lieux = telecharge(centre, a.rayon, a.sortie)
    print(f"{voies} rues et {lieux} lieux nommés enregistrés dans {a.sortie}")
