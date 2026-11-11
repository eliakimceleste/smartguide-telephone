"""Banc d'essai de la reconnaissance vocale : quel réglage de Whisper comprend
le mieux, et en combien de temps ?

Deux temps, pour comparer tous les réglages sur les MÊMES enregistrements :

1. Enregistrer une série de phrases (une seule fois par lieu de test) :
       python banc_voix.py enregistre --carte carte_zone.json --dossier essais/calme
       python banc_voix.py enregistre --carte carte_zone.json --dossier essais/rue
   Les phrases à dire sont tirées de la carte et écrites dans
   <dossier>/phrases.json (modifiable avant d'enregistrer).

2. Comparer les réglages sur ces enregistrements :
       python banc_voix.py compare --carte carte_zone.json --dossier essais/calme
   Options : --whisper-cpp <dossier de whisper.cpp> pour tester whisper.cpp
   (le moteur du téléphone) ; --moteurs pour n'en tester que certains.

Une phrase est « comprise » si le casque en tire la même commande (et la
même destination) qu'avec la phrase écrite sans faute. Résultats détaillés :
<dossier>/resultats.txt.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave

from commandes import interprete, normalise
from osm import plan_depuis_osm
from voix import FREQUENCE, _indice

ICI = os.path.dirname(os.path.abspath(__file__))
SUR_TERMUX = "com.termux" in os.environ.get("PREFIX", "")

# ---------------------------------------------------------------- phrases

COMMANDES = [
    ("Où suis-je ?", "ou_suis_je"),
    ("Répète, s'il te plaît.", "repeter"),
    ("Stop, arrête le guidage.", "arreter"),
    ("Oui.", "oui"),
    ("Non.", "non"),
    ("Quelles destinations sont possibles ?", "destinations"),
]
POLITESSE = ["Bonjour.", "Merci beaucoup."]  # ne doivent PAS devenir des destinations

FEMININS = {"pharmacie", "église", "mosquée", "boutique", "école", "banque", "station-service",
            "boulangerie", "clinique", "maternité", "salle de jeux", "auto-école", "boîte de nuit",
            "école maternelle", "gare", "poste", "mairie", "université", "bibliothèque"}


def _avec_article(mot):
    if mot[0].lower() in "aeiouyhéèêâîôû":
        return "à l'" + mot
    return ("à la " if mot in FEMININS else "au ") + mot


def lieux_de(carte, destinations=None):
    plan = plan_depuis_osm(carte, destinations)
    return {i: plan.lieux[i] for i in plan.destinations()}


def prepare_phrases(lieux, nb_types=6, nb_noms=4):
    """Phrases à dire : les commandes, des types de lieux, des lieux par leur nom,
    et deux formules de politesse."""
    from collections import Counter
    types = Counter(l.get("categorie") for l in lieux.values() if l.get("categorie"))
    types.pop("maison", None)
    phrases = [{"texte": t} for t, _ in COMMANDES]
    if "maison" in lieux:
        phrases.append({"texte": "Je veux rentrer à la maison."})
    debuts = ["Je veux aller {}.", "Emmène-moi {}.", "Je voudrais aller {}.", "Guide-moi {}."]
    for k, (t, _) in enumerate(types.most_common(nb_types)):
        phrases.append({"texte": debuts[k % len(debuts)].format(_avec_article(t))})
    noms = sorted({l["nom"] for l in lieux.values()
                   if l.get("categorie") != "maison" and len(l["nom"].split()) >= 2})
    pas = max(1, len(noms) // max(1, nb_noms))
    for nom in noms[::pas][:nb_noms]:
        phrases.append({"texte": f"Je veux aller à {nom}."})
    phrases += [{"texte": t, "politesse": True} for t in POLITESSE]
    return phrases


def attendu(phrase, lieux):
    """Ce que le casque doit comprendre : la même chose qu'avec le texte exact."""
    if phrase.get("politesse"):
        return {"type": "inconnu", "lieux": []}
    cmd = interprete(phrase["texte"], lieux)
    return {"type": cmd.type, "lieux": sorted(cmd.candidats or ([cmd.lieu] if cmd.lieu else []))}


def est_compris(transcription, att, lieux):
    cmd = interprete(transcription, lieux)
    if att["type"] == "inconnu":
        return cmd.type == "inconnu"
    if cmd.type != att["type"]:
        return False
    if att["type"] == "aller":
        return cmd.lieu in att["lieux"]
    return True


# ---------------------------------------------------------------- grammaire

def _chaine(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _variantes(s):
    """La phrase telle quelle et avec la première lettre en majuscule ou minuscule."""
    return sorted({s, s[:1].upper() + s[1:], s[:1].lower() + s[1:]})


def grammaire(lieux):
    """Grammaire GBNF pour whisper.cpp : Whisper ne peut plus écrire que des
    phrases que le casque sait traiter (commandes, destinations, politesse)."""
    commandes = ["Où suis-je", "Où je suis", "Répète", "Répète s'il te plaît", "Répète, s'il te plaît",
                 "Redis", "Pardon", "Stop", "Stop, arrête le guidage", "Arrête", "Arrête le guidage",
                 "Annule", "Oui", "Non", "D'accord", "OK", "C'est ça",
                 "Quelles destinations", "Quelles destinations sont possibles", "Où puis-je aller",
                 "Les destinations", "Aide", "Que peux-tu faire",
                 "Bonjour", "Merci", "Merci beaucoup", "Au revoir"]
    intros = ["Je veux aller", "Je voudrais aller", "Emmène-moi", "Guide-moi", "Je veux rentrer",
              "Direction", "Aller", "On va", "Allons"]
    noms = set()
    for l in lieux.values():
        for n in [l["nom"], *l.get("alias", []), l.get("categorie") or ""]:
            n = " ".join(n.split())
            if n:
                noms.add(n)
                noms.add(n.lower())
    alt = lambda elements: " | ".join(_chaine(e) for e in sorted(elements))
    lignes = [
        'root ::= " "? phrase fin',
        'fin ::= " "? [.?!]?',
        "phrase ::= commande | destination",
        "commande ::= " + alt({v for c in commandes for v in _variantes(c)}),
        'destination ::= (intro " ")? lieu',
        "intro ::= " + alt({v for i in intros for v in _variantes(i)}),
        'lieu ::= (prep " ")? article? nom',
        "prep ::= " + alt({"à", "À", "au", "Au", "aux", "vers", "chez", "Chez"}),
        "article ::= " + alt({"la ", "le ", "les ", "l'", "l’", "La ", "Le ", "L'"}),
        "nom ::= " + alt(noms),
    ]
    return "\n".join(lignes) + "\n"


# ---------------------------------------------------------------- enregistrement

def _ecrit_wav(chemin, audio):
    import numpy as np
    donnees = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(chemin, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FREQUENCE)
        w.writeframes(donnees)


def _enregistre_pc(chemin, duree_max=10.0):
    import threading

    import numpy as np
    import sounddevice as sd
    morceaux, fin = [], threading.Event()
    input("    [Entrée] pour commencer…")
    with sd.InputStream(samplerate=FREQUENCE, channels=1, dtype="float32",
                        callback=lambda d, *_: morceaux.append(d.copy())):
        time.sleep(0.3)  # le micro est ouvert AVANT qu'on dise de parler : rien n'est coupé
        print("    >>> Parlez maintenant, puis [Entrée].")
        threading.Thread(target=lambda: (input(), fin.set()), daemon=True).start()
        fin.wait(duree_max)
    audio = np.concatenate(morceaux)[:, 0] if morceaux else np.zeros(0, "float32")
    _ecrit_wav(chemin, audio)
    return len(audio) / FREQUENCE


def _enregistre_termux(chemin):
    from voix import enregistre_termux
    wav = enregistre_termux(os.path.join(tempfile.gettempdir(), "smartguide_banc"))
    if wav:
        shutil.copyfile(wav, chemin)
        with wave.open(chemin) as w:
            return w.getnframes() / w.getframerate()
    return 0.0


def commande_enregistre(args):
    os.makedirs(args.dossier, exist_ok=True)
    fichier = os.path.join(args.dossier, "phrases.json")
    lieux = lieux_de(args.carte, args.destinations)
    if os.path.exists(fichier):
        phrases = json.load(open(fichier, encoding="utf-8"))
    else:
        phrases = prepare_phrases(lieux)
        json.dump(phrases, open(fichier, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{len(phrases)} phrases à dire (liste : {fichier}).")
    print("Parlez normalement, comme dans la rue. Rien n'est envoyé sur Internet.\n")
    for k, p in enumerate(phrases, 1):
        wav = os.path.join(args.dossier, f"{k:02d}.wav")
        if os.path.exists(wav) and not args.refaire:
            continue
        print(f"[{k}/{len(phrases)}]  Dites : « {p['texte']} »")
        duree = _enregistre_termux(wav) if SUR_TERMUX else _enregistre_pc(wav)
        print(f"    ({duree:.1f} s enregistrées)\n")
    print("Terminé. Comparez maintenant les réglages :")
    print(f"  python banc_voix.py compare --carte {args.carte} --dossier {args.dossier}")


# ---------------------------------------------------------------- moteurs

class FasterWhisper:
    """Ce qu'utilise le PC aujourd'hui (--entree micro)."""

    def __init__(self, taille, indice):
        from faster_whisper import WhisperModel
        self.modele = WhisperModel(taille, device="cpu", compute_type="int8")
        self.indice = indice

    def transcrit(self, wav):
        segments, _ = self.modele.transcribe(wav, language="fr", beam_size=1,
                                             vad_filter=True, initial_prompt=self.indice)
        return " ".join(s.text.strip() for s in segments).strip()


def trouve_whisper_cli(dossier):
    for rel in ["build/bin/whisper-cli", "build/bin/Release/whisper-cli.exe", "build/bin/whisper-cli.exe",
                "Release/whisper-cli.exe", "whisper-cli.exe", "whisper-cli"]:
        chemin = os.path.join(dossier, rel)
        if os.path.isfile(chemin):
            return chemin
    return None


def trouve_modele_cpp(dossier, taille):
    for rel in [f"models/ggml-{taille}.bin", f"ggml-{taille}.bin"]:
        chemin = os.path.join(dossier, rel)
        if os.path.isfile(chemin):
            return chemin
    return None


class WhisperCppBanc:
    """Le moteur du téléphone (whisper.cpp), avec ou sans grammaire."""

    def __init__(self, programme, modele, indice, fichier_grammaire=None, fils=None):
        self.commande = [programme, "-m", modele, "-l", "fr", "-nt", "-np",
                         "-t", str(fils or os.cpu_count() or 4)]
        if indice:
            self.commande += ["--prompt", indice]
        if fichier_grammaire:
            self.commande += ["--grammar", fichier_grammaire, "--grammar-rule", "root"]

    def transcrit(self, wav):
        r = subprocess.run(self.commande + ["-f", wav], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 and not r.stdout.strip():
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "erreur")
        return " ".join(l.strip() for l in r.stdout.splitlines() if l.strip())


def moteurs_disponibles(args, indice, fichier_grammaire):
    """{nom: fonction qui crée le moteur}, seulement ceux qu'on peut lancer ici."""
    moteurs = {}
    if not SUR_TERMUX:
        try:
            import faster_whisper  # noqa: F401
            for taille in ("tiny", "base"):
                moteurs[f"faster-whisper {taille}"] = lambda t=taille: FasterWhisper(t, indice)
        except ImportError:
            print("(faster-whisper non installé : pip install faster-whisper)")
    if args.whisper_cpp:
        dossier = os.path.expanduser(args.whisper_cpp)
        programme = trouve_whisper_cli(dossier)
        if not programme:
            print(f"(whisper-cli introuvable dans {dossier})")
        else:
            for taille in ("tiny", "base"):
                modele = trouve_modele_cpp(dossier, taille)
                if not modele:
                    print(f"(modèle ggml-{taille}.bin absent de {dossier} : réglages {taille} sautés)")
                    continue
                moteurs[f"whisper.cpp {taille}"] = \
                    lambda m=modele: WhisperCppBanc(programme, m, indice, fils=args.fils)
                moteurs[f"whisper.cpp {taille} + grammaire"] = \
                    lambda m=modele: WhisperCppBanc(programme, m, indice, fichier_grammaire, args.fils)
    if args.moteurs:
        voulus = [m.strip().lower() for m in args.moteurs.split(",")]
        moteurs = {n: f for n, f in moteurs.items() if n.lower() in voulus}
    return moteurs


def commande_compare(args):
    fichier = os.path.join(args.dossier, "phrases.json")
    if not os.path.exists(fichier):
        sys.exit(f"{fichier} introuvable : lancez d'abord « python banc_voix.py enregistre ».")
    phrases = json.load(open(fichier, encoding="utf-8"))
    wavs = [os.path.join(args.dossier, f"{k:02d}.wav") for k in range(1, len(phrases) + 1)]
    essais = [(p, w) for p, w in zip(phrases, wavs) if os.path.exists(w)]
    if not essais:
        sys.exit("Aucun enregistrement trouvé.")
    lieux = lieux_de(args.carte, args.destinations)
    from collections import Counter
    types = Counter(l.get("categorie") for l in lieux.values() if l.get("categorie"))
    exemples = (["maison"] if "maison" in types else []) + \
               [t for t, _ in types.most_common() if t != "maison"][:6]
    indice = _indice(exemples)
    fichier_grammaire = os.path.join(args.dossier, "grammaire.gbnf")
    with open(fichier_grammaire, "w", encoding="utf-8") as f:
        f.write(grammaire(lieux))

    moteurs = moteurs_disponibles(args, indice, fichier_grammaire)
    if not moteurs:
        sys.exit("Aucun moteur disponible (voir les messages ci-dessus).")
    print(f"{len(essais)} enregistrements, {len(moteurs)} réglages à comparer.\n")
    bilan, details = [], []
    for nom, cree in moteurs.items():
        print(f"== {nom}")
        try:
            moteur = cree()
        except Exception as e:  # modèle impossible à charger : on passe au suivant
            print(f"   impossible de le lancer : {e}\n")
            continue
        compris, durees = 0, []
        for k, (p, wav) in enumerate(essais, 1):
            debut = time.monotonic()
            try:
                texte = moteur.transcrit(wav)
            except Exception as e:
                texte = f"[erreur : {e}]"
            durees.append(time.monotonic() - debut)
            ok = est_compris(texte, attendu(p, lieux), lieux)
            compris += ok
            ligne = f"   {'OK ' if ok else 'RATÉ'} {durees[-1]:5.1f} s  « {p['texte']} » → « {texte} »"
            print(ligne)
            details.append(f"[{nom}] {ligne.strip()}")
        bilan.append((nom, compris, len(essais), sum(durees) / len(durees), max(durees)))
        print(f"   → {compris}/{len(essais)} compris, {bilan[-1][3]:.1f} s en moyenne\n")

    titre = f"Bilan ({args.dossier}, {time.strftime('%d/%m/%Y %H:%M')})"
    tableau = [titre, "-" * len(titre),
               f"{'réglage':32} {'compris':>9} {'moyenne':>9} {'maxi':>7}"]
    for nom, c, n, moy, maxi in bilan:
        tableau.append(f"{nom:32} {c:>4}/{n:<4} {moy:>7.1f} s {maxi:>5.1f} s")
    print("\n".join(tableau))
    with open(os.path.join(args.dossier, "resultats.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(tableau) + "\n\nDétail :\n" + "\n".join(details) + "\n")
    print(f"\nDétail enregistré dans {os.path.join(args.dossier, 'resultats.txt')}")


def main():
    for flux in (sys.stdout, sys.stderr):  # console Windows : ne jamais planter sur un caractère
        try:
            flux.reconfigure(errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(description="Banc d'essai de la reconnaissance vocale de SmartGuide")
    sous = p.add_subparsers(dest="action", required=True)
    for nom, aide in (("enregistre", "enregistrer les phrases"), ("compare", "comparer les réglages")):
        s = sous.add_parser(nom, help=aide)
        s.add_argument("--carte", default=os.path.join(ICI, "exemple", "carte_exemple.json"))
        s.add_argument("--destinations", help="fichier de lieux absents d'OpenStreetMap (optionnel)")
        s.add_argument("--dossier", default=os.path.join("essais", "calme"))
    sous.choices["enregistre"].add_argument("--refaire", action="store_true",
                                            help="réenregistrer même les phrases déjà faites")
    c = sous.choices["compare"]
    c.add_argument("--whisper-cpp", help="dossier de whisper.cpp (pour tester le moteur du téléphone)")
    c.add_argument("--moteurs", help="liste séparée par des virgules, ex. « whisper.cpp tiny,whisper.cpp tiny + grammaire »")
    c.add_argument("--fils", type=int, help="whisper.cpp : nombre de fils de calcul (défaut : tous les cœurs)")
    args = p.parse_args()
    (commande_enregistre if args.action == "enregistre" else commande_compare)(args)


if __name__ == "__main__":
    main()
