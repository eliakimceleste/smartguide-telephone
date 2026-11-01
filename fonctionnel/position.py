"""Sources de position : le téléphone (via gpsd), le GPS d'Android (Termux)
ou un simulateur de marche.

Chaque source est un itérateur de Mesure (position, cap de la tête, instant).
"""
import json
import random
import socket
import subprocess
import time
from dataclasses import dataclass

import geo


@dataclass
class Mesure:
    position: tuple        # (lat, lon)
    cap: float             # cap de la tête en degrés, ou None si inconnu
    instant: float         # secondes


def gpsd(hote="127.0.0.1", port=2947):
    """Positions envoyées par le téléphone (GPSd Forwarder) et reçues par gpsd.

    Sans boussole, le cap est celui de la marche (champ « track » de gpsd),
    calculé seulement quand la personne avance.
    """
    with socket.create_connection((hote, port), timeout=10) as s:
        s.sendall(b'?WATCH={"enable":true,"json":true}\n')
        tampon = b""
        while True:
            morceau = s.recv(4096)
            if not morceau:
                return
            tampon += morceau
            while b"\n" in tampon:
                ligne, tampon = tampon.split(b"\n", 1)
                try:
                    msg = json.loads(ligne)
                except ValueError:
                    continue
                if msg.get("class") == "TPV" and "lat" in msg and "lon" in msg:
                    vitesse = msg.get("speed", 0) or 0
                    cap = msg.get("track") if vitesse > 0.4 else None
                    yield Mesure((msg["lat"], msg["lon"]), cap, time.monotonic())


def termux(intervalle=1.0):
    """GPS du téléphone Android, quand le programme tourne dans Termux.

    Utilise la commande `termux-location` (paquet termux-api et application
    Termux:API). Sans boussole, le cap est celui de la marche.
    """
    while True:
        debut = time.monotonic()
        try:
            sortie = subprocess.run(["termux-location", "-p", "gps", "-r", "once"],
                                    capture_output=True, text=True, timeout=30).stdout
            msg = json.loads(sortie)
        except (subprocess.TimeoutExpired, ValueError):
            msg = {}  # pas de position cette fois (intérieur, ciel couvert…) : on réessaie
        if isinstance(msg, dict) and "latitude" in msg and "longitude" in msg:
            cap = msg.get("bearing") if (msg.get("speed") or 0) > 0.4 else None
            yield Mesure((msg["latitude"], msg["longitude"]), cap, time.monotonic())
        attente = intervalle - (time.monotonic() - debut)
        if attente > 0:
            time.sleep(attente)


class Simulateur:
    """Une personne qui marche le long des points donnés, avec un GPS imprécis.

    `ecarts` permet de simuler une erreur de parcours : {indice_du_pas: cap_force}.
    """

    def __init__(self, points, vitesse=1.2, pas=1.0, bruit_gps=2.0, bruit_cap=8.0,
                 acceleration=1.0, graine=1, ecarts=None):
        self.points = list(points)
        self.vitesse, self.pas = vitesse, pas
        self.bruit_gps, self.bruit_cap = bruit_gps, bruit_cap
        self.acceleration = acceleration
        self.hasard = random.Random(graine)
        self.ecarts = ecarts or {}
        self.position = self.points[0]
        self.cap = geo.cap(self.points[0], self.points[1]) if len(self.points) > 1 else 0.0
        self.cible = 1
        self.instant = 0.0

    def nouveau_trajet(self, points):
        """Après un recalcul : suivre le nouvel itinéraire depuis la position actuelle."""
        self.points = list(points)
        self.cible = 1

    def __iter__(self):
        n = 0
        while True:
            if n in self.ecarts:
                self.cap = self.ecarts[n]
                self.position = geo.deplace(self.position, self.cap, self.vitesse * self.pas)
            elif self.cible < len(self.points):
                cible = self.points[self.cible]
                reste = geo.distance(self.position, cible)
                avance = self.vitesse * self.pas
                self.cap = geo.cap(self.position, cible)
                if reste <= avance:
                    self.position = cible
                    self.cible += 1
                else:
                    self.position = geo.deplace(self.position, self.cap, avance)
            self.instant += self.pas
            n += 1
            mesure = geo.deplace(self.position, self.hasard.uniform(0, 360),
                                 abs(self.hasard.gauss(0, self.bruit_gps)))
            cap = (self.cap + self.hasard.gauss(0, self.bruit_cap)) % 360
            if self.acceleration > 0:
                time.sleep(self.pas / self.acceleration)
            yield Mesure(mesure, cap, self.instant)
