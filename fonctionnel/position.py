"""Sources de position : le téléphone (via gpsd), le GPS d'Android (Termux)
ou un simulateur de marche.

Chaque source est un itérateur de Mesure (position, cap de la tête, instant).
"""
import atexit
import json
import os
import random
import socket
import subprocess
import threading
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


class _FluxTermux:
    """Positions du GPS d'Android lues en continu, en arrière-plan.

    Un fil lit `termux-location -p gps -r updates` et garde toujours la
    dernière position reçue : le guidage n'attend plus le GPS. Termux:API
    donne au plus une position toutes les 5 secondes et arrête ce mode au
    bout de 30 secondes : la commande est alors relancée aussitôt.
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._derniere = None      # dernière Mesure reçue
        self._numero = 0           # nombre de positions reçues
        self._fil = None
        self._processus = None

    def demarre(self):
        with self._condition:
            if self._fil is None:
                self._fil = threading.Thread(target=self._lit, daemon=True)
                self._fil.start()
                atexit.register(self.arrete)

    def arrete(self):
        if self._processus and self._processus.poll() is None:
            self._processus.terminate()

    def _lit(self):
        while True:
            try:
                self._processus = subprocess.Popen(
                    ["termux-location", "-p", "gps", "-r", "updates"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            except OSError:  # termux-location absent
                time.sleep(2)
                continue
            tampon = ""
            while True:
                morceau = os.read(self._processus.stdout.fileno(), 4096)
                if not morceau:
                    break  # fin des 30 secondes : on relance
                tampon = self._decoupe(tampon + morceau.decode("utf-8", "replace"))
            self._processus.wait()
            time.sleep(0.2)

    def _decoupe(self, tampon):
        """Extrait les positions complètes du texte reçu ; renvoie le reste.

        La sortie est un tableau JSON qui arrive par morceaux :
        « [ {...}, {...} ] ». On ne garde que les objets « {...} ».
        """
        decodeur = json.JSONDecoder()
        while True:
            debut = tampon.find("{")
            if debut < 0:
                return ""
            try:
                msg, fin = decodeur.raw_decode(tampon, debut)
            except ValueError:
                return tampon[debut:]  # objet incomplet : attendre la suite
            tampon = tampon[fin:]
            self._recoit(msg)

    def _recoit(self, msg):
        if isinstance(msg, dict) and "latitude" in msg and "longitude" in msg:
            cap = msg.get("bearing") if (msg.get("speed") or 0) > 0.4 else None
            mesure = Mesure((msg["latitude"], msg["longitude"]), cap, time.monotonic())
            with self._condition:
                self._derniere = mesure
                self._numero += 1
                self._condition.notify_all()

    def mesures(self, fraicheur=6.0):
        """Chaque nouvelle position, dès qu'elle arrive. Si le guidage a pris
        du retard, les positions intermédiaires sont sautées : on donne
        toujours la plus récente. Une position déjà reçue depuis moins de
        `fraicheur` secondes est donnée tout de suite."""
        self.demarre()
        with self._condition:
            recente = (self._derniere is not None
                       and time.monotonic() - self._derniere.instant < fraicheur)
            vu = self._numero - 1 if recente else self._numero
        while True:
            with self._condition:
                while self._numero == vu:
                    self._condition.wait()
                vu = self._numero
                mesure = self._derniere
            yield mesure


_flux_termux = _FluxTermux()


def termux():
    """GPS du téléphone Android, quand le programme tourne dans Termux.

    Utilise la commande `termux-location` (paquet termux-api et application
    Termux:API), lue en continu en arrière-plan. Sans boussole, le cap est
    celui de la marche.
    """
    return _flux_termux.mesures()


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
