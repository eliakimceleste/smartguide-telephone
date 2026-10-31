"""SmartGuide, partie fonctionnelle : voix -> destination -> itinéraire -> guidage vocal.

Fonctionne sur PC sans le casque. Exemples :
    python smartguide_fonctionnel.py --entree texte --voix texte       # tout au clavier
    python smartguide_fonctionnel.py                                    # micro + Whisper + gTTS, marche simulée
    python smartguide_fonctionnel.py --position gpsd --carte carte_zone.json --destinations mes_lieux.json
"""
import argparse
import os

import geo
from commandes import SEUIL_SANS_CONFIRMATION, interprete
from guidage import Guide, metres
from osm import plan_depuis_osm
from position import Simulateur, gpsd
from voix import Ecoute, Parole, Transcripteur

ICI = os.path.dirname(os.path.abspath(__file__))


class Application:
    def __init__(self, args):
        self.args = args
        self.plan = plan_depuis_osm(args.carte, args.destinations)
        self.lieux = {i: self.plan.lieux[i] for i in self.plan.destinations()}
        self.parole = Parole(args.voix)
        noms = [l["nom"] for l in self.lieux.values()]
        if args.entree == "micro":
            print("Chargement de Whisper…")
            self.ecoute = Ecoute()
            self.whisper = Transcripteur(args.modele, noms)
        depart = args.depart or next(iter(self.lieux))
        self.position = self.plan.point(depart)   # position simulée au repos
        self.cap = None
        self.dernier = ""

    # ---------- entrée ----------
    def entend(self):
        if self.args.entree == "texte":
            return input("  Vous : ")
        texte = self.whisper.transcrit(self.ecoute.enregistre())
        print(f"  Vous (transcrit) : {texte}")
        return texte

    def dit(self, texte):
        self.dernier = texte
        self.parole.dit(texte)

    # ---------- boucle principale ----------
    def lance(self):
        self.dit("Bonjour, je suis SmartGuide. Dites-moi où vous voulez aller.")
        while True:
            try:
                texte = self.entend()
            except (KeyboardInterrupt, EOFError):
                self.dit("Au revoir.")
                return
            if texte.strip().lower() in ("quitter", "q", "exit"):
                self.dit("Au revoir.")
                return
            self.traite(texte)

    def traite(self, texte):
        cmd = interprete(texte, self.lieux)
        if cmd.type == "aller":
            if cmd.lieu is None:
                self.dit("Je n'ai pas compris la destination. " + self.liste_destinations())
            elif cmd.confiance >= SEUIL_SANS_CONFIRMATION or self.confirme(cmd.lieu):
                self.guide(cmd.lieu)
            else:
                self.dit("D'accord, j'annule. " + self.liste_destinations())
        elif cmd.type == "destinations":
            self.dit(self.liste_destinations())
        elif cmd.type == "ou_suis_je":
            self.dit(self.ou_suis_je())
        elif cmd.type == "repeter":
            self.parole.dit(self.dernier or "Je n'ai encore rien dit.")
        elif cmd.type == "appeler":
            self.dit("L'appel d'un proche passera par le téléphone ; ce n'est pas encore disponible.")
        elif cmd.type == "arreter":
            self.dit("Aucun guidage en cours.")
        elif cmd.type == "aide":
            self.dit("Dites par exemple : je veux aller à la pharmacie. Vous pouvez aussi dire : "
                     "où suis-je, répète, ou stop.")
        else:
            self.dit("Je n'ai pas compris. Dites par exemple : je veux aller à "
                     f"{next(iter(self.lieux.values()))['nom'].lower()}.")

    def confirme(self, lieu):
        self.dit(f"Voulez-vous aller à : {self.lieux[lieu]['nom']} ? Répondez oui ou non.")
        for _ in range(2):
            reponse = interprete(self.entend(), self.lieux)
            if reponse.type in ("oui", "non"):
                return reponse.type == "oui"
            self.dit("Répondez oui ou non.")
        return False

    def liste_destinations(self):
        return "Vous pouvez aller à : " + ", ".join(l["nom"] for l in self.lieux.values()) + "."

    def ou_suis_je(self):
        proche = min(self.lieux, key=lambda i: geo.distance(self.position, self.plan.point(i)))
        d = geo.distance(self.position, self.plan.point(proche))
        voie, _ = self.plan.plus_proche(self.position)
        rue = self.plan.lieux[voie]["nom"] if not self.plan.lieux[voie].get("destination") else ""
        texte = (f"Vous êtes près de : {self.lieux[proche]['nom']}." if d < 10
                 else f"Vous êtes à {metres(d)} de {self.lieux[proche]['nom']}.")
        return texte + (f" Vous êtes sur {rue}." if rue else "")

    # ---------- guidage ----------
    def guide(self, lieu):
        itineraire = self.plan.itineraire(self.position, lieu)
        if itineraire is None:
            self.dit(f"Je ne trouve pas de chemin vers {self.lieux[lieu]['nom']}.")
            return
        if self.args.position == "gpsd":
            source = gpsd()
            premiere = next(source)
            self.position, self.cap = premiere.position, premiere.cap
            itineraire = self.plan.itineraire(self.position, lieu)
            simulateur = None
        else:
            ecarts = {n: 90.0 for n in range(20, 40)} if self.args.erreur else None
            simulateur = Simulateur(itineraire.points, acceleration=self.args.acceleration, ecarts=ecarts)
            source = iter(simulateur)
            self.cap = simulateur.cap
        guide = Guide(itineraire)
        self.dit(guide.depart(self.position, self.cap))
        try:
            for mesure in source:
                self.position, self.cap = mesure.position, mesure.cap
                etat = guide.mise_a_jour(mesure.position, mesure.cap, mesure.instant)
                for message in etat.messages:
                    self.dit(message)
                if etat.arrive:
                    return
                if etat.recalcul:
                    itineraire = self.plan.itineraire(mesure.position, lieu)
                    guide = Guide(itineraire)
                    if simulateur:
                        simulateur.nouveau_trajet(itineraire.points)
                    self.dit(guide.depart(mesure.position, mesure.cap))
        except KeyboardInterrupt:
            self.dit("Guidage arrêté.")


def arguments(liste=None):
    p = argparse.ArgumentParser(description="SmartGuide : voix, destination, itinéraire et guidage.")
    p.add_argument("--carte", default=os.path.join(ICI, "exemple", "carte_exemple.json"),
                   help="carte OpenStreetMap téléchargée avec osm.py")
    p.add_argument("--destinations", default=os.path.join(ICI, "exemple", "destinations_exemple.json"))
    p.add_argument("--entree", choices=["micro", "texte"], default="micro",
                   help="micro = Whisper ; texte = taper les commandes")
    p.add_argument("--voix", choices=["gtts", "hors_ligne", "texte"], default="gtts")
    p.add_argument("--modele", default="tiny", help="taille de Whisper : tiny, base, small")
    p.add_argument("--position", choices=["simulation", "gpsd"], default="simulation")
    p.add_argument("--depart", help="simulation : identifiant du lieu de départ")
    p.add_argument("--acceleration", type=float, default=3.0,
                   help="simulation : vitesse de la marche simulée (0 = sans attente)")
    p.add_argument("--erreur", action="store_true", help="simulation : s'écarter du trajet pour tester le recalcul")
    return p.parse_args(liste)


if __name__ == "__main__":
    Application(arguments()).lance()
