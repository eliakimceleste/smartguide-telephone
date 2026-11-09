"""SmartGuide, partie fonctionnelle : voix -> destination -> itinéraire -> guidage vocal.

Fonctionne sur PC sans le casque. Exemples :
    python smartguide_fonctionnel.py --entree texte --voix texte       # tout au clavier
    python smartguide_fonctionnel.py                                    # micro + Whisper + gTTS, marche simulée
    python smartguide_fonctionnel.py --carte carte_zone.json                # votre zone (lieux pris dans OpenStreetMap)
"""
import argparse
import os
import shutil

import geo
from collections import Counter

from commandes import SEUIL_SANS_CONFIRMATION, candidats_destination, interprete
from guidage import Guide, metres
from osm import plan_depuis_osm
from position import Simulateur, gpsd, termux
from voix import Ecoute, Parole, Transcripteur, WhisperCpp, ecoute_android, enregistre_termux

ICI = os.path.dirname(os.path.abspath(__file__))


class Application:
    def __init__(self, args):
        self.args = args
        self.plan = plan_depuis_osm(args.carte, args.destinations)
        self.lieux = {i: self.plan.lieux[i] for i in self.plan.destinations()}
        self.parole = Parole(args.voix)
        if args.entree == "micro":
            print("Chargement de Whisper…")
            self.ecoute = Ecoute()
            self.whisper = Transcripteur(args.modele, self.exemples_de_lieux())
        elif args.entree == "termux":
            self.whisper = WhisperCpp(os.path.expanduser(args.whisper_cpp), args.modele,
                                      self.exemples_de_lieux())
        self.position = self.plan.point(self.lieu_de_depart())   # position simulée au repos
        self.cap = None
        self.dernier = ""

    def lieu_de_depart(self):
        """--depart accepte un identifiant ou un nom (« maison », « pharmacie les cocotiers »)."""
        if self.args.depart in self.lieux:
            return self.args.depart
        if self.args.depart:
            candidats, _ = candidats_destination(self.args.depart, self.lieux)
            if candidats:
                return candidats[0]
        return "maison" if "maison" in self.lieux else next(iter(self.lieux))

    def exemples_de_lieux(self, combien=6):
        """Maison, les types de lieux les plus courants, puis les lieux personnels sans type."""
        types = Counter(l.get("categorie") for l in self.lieux.values() if l.get("categorie"))
        exemples = ["maison"] if "maison" in types else []
        exemples += [t for t, _ in types.most_common() if t != "maison"][:combien]
        exemples += [l["nom"] for l in self.lieux.values() if not l.get("categorie")][:3]
        return exemples

    # ---------- entrée ----------
    def entend(self):
        self.parole.attend()  # ne pas enregistrer le micro pendant que le casque parle
        if self.args.entree == "texte":
            return input("  Vous : ")
        if self.args.entree == "android":
            texte = ecoute_android()
            print(f"  Vous (reconnu par Android) : {texte}")
            return texte
        if self.args.entree == "termux":
            texte = self.whisper.transcrit(enregistre_termux(os.path.join(self.parole.cache, "micro")))
            print(f"  Vous (transcrit par Whisper en {self.whisper.duree:.1f} s) : {texte}")
            return texte
        texte = self.whisper.transcrit(self.ecoute.enregistre())
        print(f"  Vous (transcrit) : {texte}")
        return texte

    def dit(self, texte):
        self.dernier = texte
        self.parole.dit(texte)

    def dit_en_fond(self, phrases):
        """Pendant le guidage avec le vrai GPS : parler sans arrêter de lire
        les positions. En simulation, les phrases sont dites une à une comme
        avant (la marche simulée attend la voix, aucune consigne n'est sautée)."""
        if not phrases:
            return
        if self.args.position == "simulation":
            for texte in phrases:
                self.dit(texte)
            return
        self.dernier = phrases[-1]
        self.parole.dit_en_fond(phrases)

    # ---------- boucle principale ----------
    def lance(self):
        print(f"  ({len(self.lieux)} destinations chargées"
              + (f", {len(self.plan.ignores)} ignorées car trop loin d'une rue)" if self.plan.ignores else ")"))
        if self.args.position != "simulation":
            print("  (Recherche de la position GPS…)")
            premiere = next(gpsd() if self.args.position == "gpsd" else termux())
            self.position = premiere.position
            print(f"  (Position trouvée : à {metres(geo.distance(self.position, self.plan.point(self.plan.plus_proche(self.position)[0])))} d'une rue de la carte)")
        if self.args.position == "simulation":
            depart = min(self.lieux, key=lambda i: geo.distance(self.position, self.plan.point(i)))
            print(f"  (Marche simulée : départ de {self.lieux[depart]['nom']} ; option --depart pour changer)")
        if self.args.voix == "fichier":
            print(f"  (Les phrases sont enregistrées en mp3 dans {self.parole.sortie})")
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
            else:
                lieu = self.plus_proche(cmd.candidats or [cmd.lieu])
                if cmd.confiance >= SEUIL_SANS_CONFIRMATION or self.confirme(lieu):
                    self.guide(lieu)
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
            self.dit("Je n'ai pas compris. " + self.liste_destinations())

    def confirme(self, lieu):
        self.dit(f"Voulez-vous aller à : {self.lieux[lieu]['nom']} ? Répondez oui ou non.")
        for _ in range(2):
            reponse = interprete(self.entend(), self.lieux)
            if reponse.type in ("oui", "non"):
                return reponse.type == "oui"
            self.dit("Répondez oui ou non.")
        return False

    def plus_proche(self, candidats):
        """Parmi plusieurs lieux du même type, le plus proche de la position."""
        lieu = min(candidats, key=lambda i: geo.distance(self.position, self.plan.point(i)))
        if len(candidats) > 1:
            print(f"  ({len(candidats)} lieux possibles, le plus proche est choisi)")
        return lieu

    def liste_destinations(self):
        return ("Dites par exemple : " + ", ".join(self.exemples_de_lieux())
                + ", ou le nom d'un lieu.")

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
        if itineraire.longueur() < 8:
            self.dit(f"Vous êtes déjà à : {self.lieux[lieu]['nom']}.")
            return
        if self.args.position in ("gpsd", "termux"):
            print("  (Recherche de la position GPS…)")
            source = gpsd() if self.args.position == "gpsd" else termux()
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
        self.dit_en_fond([guide.depart(self.position, self.cap)])
        try:
            for mesure in source:
                self.position, self.cap = mesure.position, mesure.cap
                etat = guide.mise_a_jour(mesure.position, mesure.cap, mesure.instant)
                phrases = list(etat.messages)
                if etat.recalcul and not etat.arrive:
                    itineraire = self.plan.itineraire(mesure.position, lieu)
                    guide = Guide(itineraire)
                    if simulateur:
                        simulateur.nouveau_trajet(itineraire.points)
                    phrases.append(guide.depart(mesure.position, mesure.cap))
                self.dit_en_fond(phrases)
                if etat.arrive:
                    return
        except KeyboardInterrupt:
            self.dit("Guidage arrêté.")


def arguments(liste=None):
    p = argparse.ArgumentParser(description="SmartGuide : voix, destination, itinéraire et guidage.")
    p.add_argument("--carte", default=os.path.join(ICI, "exemple", "carte_exemple.json"),
                   help="carte OpenStreetMap téléchargée avec osm.py")
    p.add_argument("--destinations", help="optionnel : fichier de lieux absents d'OpenStreetMap")
    p.add_argument("--entree", choices=["micro", "texte", "android", "termux"], default="micro",
                   help="micro = Whisper ; texte = taper les commandes ; "
                        "termux = micro du téléphone + Whisper (whisper.cpp), en français ; "
                        "android = reconnaissance vocale d'Android (en anglais seulement)")
    p.add_argument("--voix", choices=["gtts", "android", "hors_ligne", "texte", "fichier"],
                   default="android" if shutil.which("termux-tts-speak") else "gtts",
                   help="android = voix d'Android, sans Internet (défaut sur le téléphone) ; "
                        "gtts = voix Google (défaut sur PC) ; "
                        "fichier = phrases gTTS enregistrées en mp3 (utile sur un serveur sans haut-parleur)")
    p.add_argument("--modele", default="tiny", help="taille de Whisper : tiny, base, small")
    p.add_argument("--whisper-cpp", default="~/whisper.cpp",
                   help="--entree termux : dossier de whisper.cpp")
    p.add_argument("--position", choices=["simulation", "gpsd", "termux"], default="simulation",
                   help="termux = GPS du téléphone Android")
    p.add_argument("--depart", help="simulation : lieu de départ, par son nom (défaut : maison)")
    p.add_argument("--acceleration", type=float, default=3.0,
                   help="simulation : vitesse de la marche simulée (0 = sans attente)")
    p.add_argument("--erreur", action="store_true", help="simulation : s'écarter du trajet pour tester le recalcul")
    return p.parse_args(liste)


if __name__ == "__main__":
    Application(arguments()).lance()
