"""Calcul de l'itinéraire à pied, sans Internet.

Le plan (lieux reliés par des chemins) vient de la carte OpenStreetMap
téléchargée une fois (voir osm.py) ; le plus court chemin est calculé sur
la carte elle-même avec l'algorithme de Dijkstra.
"""
import heapq
import json

import geo


class Plan:
    """Lieux (points nommés) reliés par des chemins praticables à pied."""

    def __init__(self, lieux, chemins, titre=""):
        self.titre = titre
        self.lieux = lieux
        self.voisins = {ident: [] for ident in lieux}
        for a, b in chemins:
            d = geo.distance(self.point(a), self.point(b))
            self.voisins[a].append((b, d))
            self.voisins[b].append((a, d))

    @classmethod
    def charge(cls, chemin_fichier):
        with open(chemin_fichier, encoding="utf-8") as f:
            donnees = json.load(f)
        return cls(donnees["lieux"], donnees["chemins"], donnees.get("nom", ""))

    def point(self, ident):
        lieu = self.lieux[ident]
        return (lieu["lat"], lieu["lon"])

    def nom(self, ident):
        return self.lieux[ident]["nom"]

    def destinations(self):
        return [i for i, l in self.lieux.items() if l.get("destination", True)]

    def plus_proche(self, position):
        """Identifiant du lieu le plus proche et sa distance."""
        return min(((i, geo.distance(position, self.point(i))) for i in self.lieux),
                   key=lambda t: t[1])

    def chemin(self, depart, arrivee):
        """Plus court chemin (Dijkstra) : liste d'identifiants, ou None."""
        distances, precedent = {depart: 0.0}, {}
        file = [(0.0, depart)]
        while file:
            d, ident = heapq.heappop(file)
            if ident == arrivee:
                break
            if d > distances[ident]:
                continue
            for voisin, longueur in self.voisins[ident]:
                nd = d + longueur
                if nd < distances.get(voisin, float("inf")):
                    distances[voisin], precedent[voisin] = nd, ident
                    heapq.heappush(file, (nd, voisin))
        if arrivee not in distances:
            return None
        etapes = [arrivee]
        while etapes[-1] != depart:
            etapes.append(precedent[etapes[-1]])
        return etapes[::-1]

    def itineraire(self, position, arrivee, seuil_depart=8.0):
        """Points (lat, lon) de la position actuelle jusqu'à la destination.

        Le trajet commence au lieu du plan le plus proche ; si la personne en
        est à plus de `seuil_depart` mètres, on l'y conduit d'abord en ligne droite.
        """
        depart, ecart = self.plus_proche(position)
        etapes = self.chemin(depart, arrivee)
        if etapes is None:
            return None
        points = [self.point(i) for i in etapes]
        noms = [self.nom(i) for i in etapes]
        if ecart > seuil_depart:
            points.insert(0, position)
            noms.insert(0, "votre position")
        elif len(points) == 1:
            points.insert(0, position)
            noms.insert(0, "votre position")
        else:
            points[0] = position
        return Itineraire(points, noms, self.nom(arrivee))


class Itineraire:
    def __init__(self, points, noms, destination):
        self.points = points          # [(lat, lon), ...], le premier = départ
        self.noms = noms              # nom de chaque point (pour le débogage)
        self.destination = destination

    def longueur(self):
        return sum(geo.distance(a, b) for a, b in zip(self.points, self.points[1:]))

