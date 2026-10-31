"""Guidage pas à pas : transforme la position et l'orientation de la tête
en consignes courtes à dire à la personne.

Le Guide ne parle pas lui-même : `mise_a_jour` renvoie les phrases à dire,
ce qui permet de le tester sans son.
"""
from dataclasses import dataclass, field

import geo


def metres(d):
    """Distance arrondie, dite simplement : « 7 mètres », « 45 mètres »."""
    d = max(1, round(d) if d < 10 else 5 * round(d / 5))
    return f"{d} mètre" if d == 1 else f"{d} mètres"


def mot_direction(angle):
    """Angle relatif (-180 à 180) vers des mots : « à gauche », « tout droit »…"""
    a = abs(angle)
    if a <= 20:
        return "tout droit"
    cote = "à droite" if angle > 0 else "à gauche"
    if a <= 60:
        return f"légèrement {cote}"
    if a <= 135:
        return cote
    return "demi-tour"


def phrase_orientation(mot):
    return "Faites demi-tour." if mot == "demi-tour" else f"Orientez-vous {mot}."


def phrase_virage(angle, infinitif=False):
    mot = mot_direction(angle)
    if mot == "demi-tour":
        return "faire demi-tour" if infinitif else "faites demi-tour"
    return f"tourner {mot}" if infinitif else f"tournez {mot}"


@dataclass
class Etat:
    messages: list = field(default_factory=list)
    recalcul: bool = False   # la personne s'est écartée : recalculer l'itinéraire
    arrive: bool = False


class Guide:
    def __init__(self, itineraire, seuil_arrivee=6.0, seuil_virage=30.0, preavis=12.0,
                 ecart_max=20.0, rappel=25.0, confirmations=3, distance_min_correction=12.0):
        self.itineraire = itineraire
        self.points = itineraire.points
        self.seuil_arrivee = seuil_arrivee
        self.preavis = preavis
        self.ecart_max = ecart_max
        self.rappel = rappel
        self.confirmations = confirmations
        self.distance_min_correction = distance_min_correction
        self.silence_jusqua = 0.0         # pas de correction juste après un virage
        self.candidat, self.vu = None, 0  # direction observée plusieurs fois avant d'être dite
        self.i = 1                      # indice du prochain point à atteindre
        self.arrive = False
        self.preavis_faits = set()
        self.derniere_direction = "tout droit"
        self.dernier_message = None     # instant du dernier message (secondes)
        self.dernier_texte = ""
        # Angle de virage à chaque point intermédiaire ; on n'annonce que les vrais virages.
        self.virages = {}
        for k in range(1, len(self.points) - 1):
            avant = geo.cap(self.points[k - 1], self.points[k])
            apres = geo.cap(self.points[k], self.points[k + 1])
            angle = geo.angle_relatif(apres, avant)
            if abs(angle) >= seuil_virage:
                self.virages[k] = angle

    def _reste_jusqua(self, position, k):
        """Distance à parcourir depuis la position jusqu'au point k."""
        d = geo.distance(position, self.points[self.i])
        for j in range(self.i, k):
            d += geo.distance(self.points[j], self.points[j + 1])
        return d

    def _prochain_virage(self):
        for k in sorted(self.virages):
            if k >= self.i:
                return k
        return None

    def depart(self, position, cap_tete=None):
        """Première phrase : destination, longueur, direction de départ."""
        fin = len(self.points) - 1
        texte = (f"Direction {self.itineraire.destination}, "
                 f"{metres(self._reste_jusqua(position, fin))} environ.")
        if cap_tete is not None:
            angle = geo.angle_relatif(geo.cap(position, self.points[self.i]), cap_tete)
            mot = mot_direction(angle)
            texte += " Avancez tout droit." if mot == "tout droit" else " " + phrase_orientation(mot)
            self.derniere_direction = mot
        else:
            texte += " Avancez, je vous indiquerai la direction."
        return texte

    def mise_a_jour(self, position, cap_tete, instant):
        """Appelée à chaque nouvelle position. Renvoie un Etat."""
        etat = Etat()
        if self.arrive:
            etat.arrive = True
            return etat
        fin = len(self.points) - 1

        # 1. Points atteints (ou dépassés quand le GPS saute un point).
        virage_annonce = False
        while self.i <= fin:
            proche = geo.distance(position, self.points[self.i]) < self.seuil_arrivee
            depasse = (self.i < fin
                       and geo.ecart_segment(position, self.points[self.i], self.points[self.i + 1]) < 5
                       and geo.distance(position, self.points[self.i + 1])
                       < geo.distance(self.points[self.i], self.points[self.i + 1]))
            if not (proche or depasse):
                break
            if self.i == fin:
                self.arrive = True
                etat.arrive = True
                etat.messages.append(f"Destination atteinte : {self.itineraire.destination}.")
                return self._dit(etat, instant)
            if self.i in self.virages:
                etat.messages.append(f"{phrase_virage(self.virages[self.i]).capitalize()} maintenant.")
                virage_annonce = True
            self.i += 1

        # 2. Trop loin du trajet : il faut recalculer.
        if geo.ecart_segment(position, self.points[self.i - 1], self.points[self.i]) > self.ecart_max:
            etat.recalcul = True
            etat.messages.append("Vous avez quitté le trajet, je recalcule.")
            return self._dit(etat, instant)

        # 3. Préavis avant le prochain virage.
        k = self._prochain_virage()
        if k is not None and k not in self.preavis_faits:
            reste = self._reste_jusqua(position, k)
            if reste <= self.preavis + self.seuil_arrivee:
                self.preavis_faits.add(k)
                etat.messages.append(f"Dans {metres(reste)}, {phrase_virage(self.virages[k])}.")

        # 4. La tête n'est pas tournée vers le prochain point : corriger.
        # Juste après « tournez maintenant », on laisse le temps de tourner.
        if virage_annonce:
            self.derniere_direction = "tout droit"
            self.silence_jusqua = instant + 8
        elif cap_tete is not None and instant >= self.silence_jusqua and \
                geo.distance(position, self.points[self.i]) >= self.distance_min_correction:
            # Près du point, le cap vers lui varie trop avec l'imprécision du GPS.
            # Une direction n'est dite que si elle se répète (`confirmations` fois).
            angle = geo.angle_relatif(geo.cap(position, self.points[self.i]), cap_tete)
            mot = mot_direction(angle)
            self.vu = self.vu + 1 if mot == self.candidat else 1
            self.candidat = mot
            if self.vu >= self.confirmations and mot != self.derniere_direction:
                if mot != "tout droit":
                    etat.messages.append(phrase_orientation(mot))
                self.derniere_direction = mot

        # 5. Rappel régulier si rien n'a été dit depuis longtemps.
        if not etat.messages and self.dernier_message is not None \
                and instant - self.dernier_message >= self.rappel:
            if k is None:
                etat.messages.append(f"Continuez, la destination est à {metres(self._reste_jusqua(position, fin))}.")
            else:
                etat.messages.append(f"Continuez, encore {metres(self._reste_jusqua(position, k))} "
                                     f"avant de {phrase_virage(self.virages[k], infinitif=True)}.")
        return self._dit(etat, instant)

    def _dit(self, etat, instant):
        if self.dernier_message is None or etat.messages:
            self.dernier_message = instant
        if etat.messages:
            self.dernier_texte = " ".join(etat.messages)
        return etat
