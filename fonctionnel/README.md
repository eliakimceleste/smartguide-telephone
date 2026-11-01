# SmartGuide : partie fonctionnelle

Voix → destination → itinéraire → guidage vocal, testable sur PC sans le casque.

1. **Reconnaissance vocale** : Whisper (faster-whisper, modèle `tiny` par défaut), en français.
2. **Destination** : la phrase est comparée aux noms de vos lieux, en tolérant les erreurs
   de transcription (« farmacie » → Pharmacie). En cas de doute, SmartGuide demande « oui ou non ».
3. **Itinéraire** : plus court chemin à pied sur la carte OpenStreetMap téléchargée une fois
   (aucun Internet nécessaire ensuite).
4. **Guidage** : consignes courtes (« Dans 15 mètres, tournez à droite »), corrections
   d'orientation, recalcul si la personne quitte le trajet.
5. **Voix** : gTTS comme dans le mémoire (phrases gardées en cache), voix hors ligne en secours.

## Installation

```bash
cd fonctionnel
python -m venv venv && source venv/bin/activate      # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

Pour entendre gTTS sous Linux : `sudo apt install mpg123`. Au premier lancement avec le micro,
Whisper télécharge son modèle (environ 75 Mo pour `tiny`).

## Essayer tout de suite (carte d'exemple, coordonnées fictives)

```bash
python smartguide_fonctionnel.py --entree texte --voix texte    # tout au clavier, réponses à l'écran
python smartguide_fonctionnel.py --entree texte                 # au clavier, réponses avec gTTS
python smartguide_fonctionnel.py                                # micro + Whisper + gTTS
python smartguide_fonctionnel.py --entree texte --voix texte --erreur   # tester le recalcul
python smartguide_fonctionnel.py --entree texte --voix fichier --depart marche   # sur un serveur
```

**Sur un serveur** (sans haut-parleur ni micro), le son ne peut pas sortir : `--voix fichier`
enregistre chaque phrase gTTS en mp3 dans `voix_sortie/`, à télécharger pour l'écouter.
Le micro et la voix en direct se testent sur votre ordinateur.

Avec le micro : **Entrée** pour parler, **Entrée** quand vous avez fini.
La marche est simulée (option `--acceleration` pour aller plus ou moins vite, `0` = instantané).
**Ctrl+C** arrête un guidage ; `quitter` ferme le programme.

Phrases comprises : « je veux aller à la pharmacie », « emmène-moi au marché », « où suis-je »,
« quelles destinations », « répète », « stop », « oui », « non ».

## Passer à votre zone

1. Télécharger la carte autour de chez vous : latitude,longitude de la maison (clic droit
   sur Google Maps) et rayon en mètres (distance du lieu le plus loin + 200 m environ) :
   ```bash
   python osm.py --centre 6.4170,2.3420 --rayon 1000 --sortie carte_zone.json
   ```
   La carte contient les rues **et les lieux nommés** d'OpenStreetMap (pharmacies, églises,
   mosquées, marchés, écoles, boutiques…) : ce sont les destinations, rien à saisir.
   Le centre devient la destination « Maison » (« chez moi »).
2. Lancer :
   ```bash
   python smartguide_fonctionnel.py --carte carte_zone.json
   ```
   « emmène-moi à la pharmacie » choisit la pharmacie la plus proche ; le nom exact
   (« la pharmacie Les Cocotiers ») choisit ce lieu-là. `--depart` accepte un nom de lieu.

Ce que SmartGuide connaît = ce qu'affiche openstreetmap.org sur votre quartier. Un lieu
manquant : l'ajouter sur openstreetmap.org (puis retélécharger), ou dans un petit fichier
optionnel sur le modèle de `exemple/mes_lieux_exemple.json`, donné avec `--destinations`.
Les mots dits pour chaque type de lieu sont dans `categories_osm.json`, modifiable.

`carte_zone.json` et `mes_lieux.json` contiennent la position de votre maison : ils sont
ignorés par Git pour ne pas être publiés.

## Avec la vraie position du téléphone

Le téléphone envoie sa position GPS à l'application GPSd Forwarder, reçue par `gpsd` sur le PC
(ou plus tard sur la carte du casque) :

```bash
sudo apt install gpsd
sudo gpsd -N -n udp://0.0.0.0:29998        # même port que dans GPSd Forwarder
python smartguide_fonctionnel.py --position gpsd --carte carte_zone.json
```

Sans boussole, l'orientation vient du sens de la marche : elle n'est connue que quand on avance.

## Tests

```bash
python -m pytest -q tests
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `smartguide_fonctionnel.py` | programme principal |
| `voix.py` | micro, Whisper, gTTS |
| `commandes.py` | comprendre la phrase et la destination |
| `osm.py` | télécharger la carte (rues et lieux) et en faire un plan |
| `categories_osm.json` | mot dit pour chaque type de lieu OpenStreetMap |
| `itineraire.py` | plus court chemin (Dijkstra) |
| `guidage.py` | consignes pas à pas |
| `position.py` | position du téléphone (gpsd) ou marche simulée |
| `geo.py` | distances et caps |
