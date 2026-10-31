"""Carte OpenStreetMap : téléchargement (une fois, avec Internet) et
transformation en plan pour le calcul d'itinéraire (sans Internet).

Usage, sur un PC connecté :
    python osm.py --centre 6.4170,2.3420 --rayon 1000 --sortie carte_zone.json
"""
import argparse
import json

import geo
from itineraire import Plan

OVERPASS = "https://overpass-api.de/api/interpreter"

# Toutes les voies où l'on peut marcher : allées, trottoirs, rues, sentiers.
# On exclut autoroutes et voies interdites aux piétons.
REQUETE = """
[out:json][timeout:90];
(
  way["highway"]["highway"!~"^(motorway|motorway_link|trunk|trunk_link|construction|proposed)$"]
     ["foot"!~"^(no|private)$"]["access"!~"^(no|private)$"]({s},{w},{n},{e});
);
(._;>;);
out body;
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

    s, w, n, e = boite(centre, rayon)
    requete = REQUETE.format(s=s, w=w, n=n, e=e)
    r = requests.post(OVERPASS, data={"data": requete}, timeout=120,
                      headers={"User-Agent": "SmartGuide (projet de memoire)"})
    r.raise_for_status()
    donnees = r.json()
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False)
    voies = sum(1 for el in donnees["elements"] if el["type"] == "way")
    noeuds = sum(1 for el in donnees["elements"] if el["type"] == "node")
    return voies, noeuds


def plan_depuis_osm(fichier_carte, fichier_destinations, liaison_max=80.0):
    """Construit le Plan : les points des voies OSM, plus les destinations.

    Chaque destination est reliée au point de voie le plus proche (à moins
    de `liaison_max` mètres), ce qui couvre les entrées de bâtiments que la
    carte ne dessine pas.
    """
    with open(fichier_carte, encoding="utf-8") as f:
        elements = json.load(f)["elements"]
    with open(fichier_destinations, encoding="utf-8") as f:
        destinations = json.load(f)["destinations"]

    noeuds = {el["id"]: (el["lat"], el["lon"]) for el in elements if el["type"] == "node"}
    lieux, chemins = {}, []
    for el in elements:
        if el["type"] != "way":
            continue
        ids = [i for i in el["nodes"] if i in noeuds]
        for a, b in zip(ids, ids[1:]):
            for i in (a, b):
                ident = f"osm{i}"
                if ident not in lieux:
                    lat, lon = noeuds[i]
                    lieux[ident] = {"nom": el.get("tags", {}).get("name", ""),
                                    "lat": lat, "lon": lon, "destination": False}
            chemins.append((f"osm{a}", f"osm{b}"))
    if not lieux:
        raise ValueError("La carte ne contient aucune voie praticable à pied.")

    voies = list(lieux)
    for ident, dest in destinations.items():
        point = (dest["lat"], dest["lon"])
        proche = min(voies, key=lambda v: geo.distance(point, (lieux[v]["lat"], lieux[v]["lon"])))
        ecart = geo.distance(point, (lieux[proche]["lat"], lieux[proche]["lon"]))
        if ecart > liaison_max:
            raise ValueError(f"« {dest['nom']} » est à {ecart:.0f} m de la voie la plus proche : "
                             "vérifier ses coordonnées ou ajouter l'allée sur OpenStreetMap.")
        lieux[ident] = {"nom": dest["nom"], "lat": dest["lat"], "lon": dest["lon"],
                        "alias": dest.get("alias", []), "destination": True}
        chemins.append((ident, proche))
    return Plan(lieux, chemins, titre=fichier_carte)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Télécharge la carte OpenStreetMap autour d'un point.")
    p.add_argument("--centre", required=True, help="latitude,longitude du centre, ex. 6.4170,2.3420")
    p.add_argument("--rayon", type=float, default=1000, help="rayon en mètres (défaut 1000)")
    p.add_argument("--sortie", default="carte_zone.json")
    a = p.parse_args()
    centre = tuple(float(x) for x in a.centre.split(","))
    voies, noeuds = telecharge(centre, a.rayon, a.sortie)
    print(f"{voies} voies et {noeuds} points enregistrés dans {a.sortie}")
