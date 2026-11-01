"""Comprendre la phrase transcrite : quelle commande, et quelle destination.

Aucune dépendance : la comparaison approximative utilise difflib, pour
tolérer les petites erreurs de transcription (« bibliotec », « cafeteria »).
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass


def normalise(texte):
    """Minuscules, sans accents ni ponctuation."""
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9 ]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


# Mots-clés de chaque commande, déjà normalisés. L'ordre compte :
# la première commande trouvée gagne.
MOTS_CLES = [
    ("arreter", ["arrete", "arreter", "stop", "annule", "annuler"]),
    ("ou_suis_je", ["ou suis je", "ou je suis", "ou est ce que je suis", "ma position"]),
    ("repeter", ["repete", "repeter", "redis", "pardon"]),
    ("destinations", ["quelles destinations", "liste des destinations", "ou puis je aller",
                      "les destinations", "destinations possibles"]),
    ("appeler", ["appelle", "appeler", "urgence", "au secours", "aide moi"]),
    ("aide", ["aide", "que peux tu faire", "comment ca marche"]),
    ("oui", ["oui", "d accord", "ok", "exact", "c est ca", "voila"]),
    ("non", ["non", "pas ca", "faux"]),
]

# Expressions qui annoncent une destination.
INTRO_DESTINATION = ["je veux aller a", "je veux aller au", "je voudrais aller a", "emmene moi a",
                     "emmene moi au", "emmene moi vers", "guide moi vers", "guide moi a", "aller a",
                     "aller au", "direction", "vers", "va a", "allons a", "on va a", "a la", "au"]

SEUIL_DESTINATION = 0.6   # en dessous, on considère que ce n'est pas une destination
SEUIL_SANS_CONFIRMATION = 0.85  # au-dessus, pas besoin de demander confirmation


@dataclass
class Commande:
    type: str                 # aller, arreter, ou_suis_je, repeter, destinations, appeler, aide, oui, non, inconnu
    texte: str
    lieu: str = None          # identifiant du lieu pour « aller »
    confiance: float = 0.0    # 0 à 1, qualité de la reconnaissance du lieu
    candidats: list = None    # tous les lieux possibles (ex. toutes les pharmacies)


def _contient(texte, expression):
    return re.search(rf"\b{re.escape(expression)}\b", texte) is not None


def _score(morceau, nom):
    """Ressemblance entre un morceau de phrase et un nom de lieu (0 à 1)."""
    if not morceau or not nom:
        return 0.0
    if _contient(morceau, nom):
        # Un nom long contenu dans la phrase l'emporte sur un nom court :
        # « pharmacie les cocotiers » préfère ce lieu précis à « pharmacie ».
        return 1.0 + len(nom) / 1000
    meilleur = difflib.SequenceMatcher(None, morceau, nom).ratio()
    # Compare aussi avec chaque groupe de mots de la même longueur que le nom.
    mots, n = morceau.split(), len(nom.split())
    for i in range(len(mots) - n + 1):
        groupe = " ".join(mots[i:i + n])
        meilleur = max(meilleur, difflib.SequenceMatcher(None, groupe, nom).ratio())
    return meilleur


def candidats_destination(texte, lieux):
    """Renvoie ([identifiants à égalité], confiance) des lieux qui ressemblent
    le plus à la phrase. Plusieurs lieux à égalité = même type de lieu
    (« la pharmacie ») : l'application choisit alors le plus proche."""
    phrase = normalise(texte)
    for intro in sorted(INTRO_DESTINATION, key=len, reverse=True):
        if phrase.startswith(intro + " ") or f" {intro} " in f" {phrase} ":
            phrase = phrase.split(intro, 1)[1].strip() or phrase
            break
    phrase = re.sub(r"^(la|le|l|les|du|de la|des) ", "", phrase)
    scores = {}
    for ident, lieu in lieux.items():
        if not lieu.get("destination", True):
            continue
        for nom in [lieu["nom"], *lieu.get("alias", [])]:
            nom = re.sub(r"^(la|le|l|les) ", "", normalise(nom))
            scores[ident] = max(scores.get(ident, 0.0), _score(phrase, nom))
    if not scores:
        return [], 0.0
    meilleur = max(scores.values())
    if meilleur < SEUIL_DESTINATION:
        return [], min(meilleur, 1.0)
    return [i for i, sc in scores.items() if sc >= meilleur - 1e-9], min(meilleur, 1.0)


def trouve_destination(texte, lieux):
    """Renvoie (identifiant, confiance) du lieu le plus ressemblant, ou (None, confiance)."""
    candidats, confiance = candidats_destination(texte, lieux)
    return (candidats[0] if candidats else None), confiance


def interprete(texte, lieux):
    """Transforme la phrase en Commande."""
    phrase = normalise(texte)
    if not phrase:
        return Commande("inconnu", texte)
    for type_, mots in MOTS_CLES:
        if any(_contient(phrase, m) for m in mots):
            # « aide-moi à aller à la bibliothèque » reste une demande de destination.
            if type_ in ("aide", "appeler", "oui", "non"):
                candidats, conf = candidats_destination(texte, lieux)
                if candidats and conf >= SEUIL_SANS_CONFIRMATION:
                    return Commande("aller", texte, candidats[0], conf, candidats)
            return Commande(type_, texte)
    candidats, conf = candidats_destination(texte, lieux)
    if candidats:
        return Commande("aller", texte, candidats[0], conf, candidats)
    if any(_contient(phrase, m) for m in ["aller", "emmene", "guide", "direction"]):
        return Commande("aller", texte, None, conf)  # destination demandée mais pas comprise
    return Commande("inconnu", texte, confiance=conf)
