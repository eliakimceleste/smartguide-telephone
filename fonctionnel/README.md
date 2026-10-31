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
```

Avec le micro : **Entrée** pour parler, **Entrée** quand vous avez fini.
La marche est simulée (option `--acceleration` pour aller plus ou moins vite, `0` = instantané).
**Ctrl+C** arrête un guidage ; `quitter` ferme le programme.

Phrases comprises : « je veux aller à la pharmacie », « emmène-moi au marché », « où suis-je »,
« quelles destinations », « répète », « stop », « oui », « non ».

## Passer à votre zone

1. Télécharger la carte autour de chez vous (latitude,longitude copiée depuis Google Maps
   ou OpenStreetMap ; rayon en mètres) :
   ```bash
   python osm.py --centre 6.4170,2.3420 --rayon 1000 --sortie carte_zone.json
   ```
2. Copier `exemple/destinations_exemple.json` en `mes_lieux.json` et y mettre vos 4 ou 5 lieux :
   nom, autres façons de le dire (`alias`), latitude et longitude de l'entrée.
3. Lancer :
   ```bash
   python smartguide_fonctionnel.py --carte carte_zone.json --destinations mes_lieux.json --depart maison
   ```

Si un lieu est à plus de 80 m d'une rue de la carte, le programme le signale : vérifier ses
coordonnées, ou ajouter la ruelle sur openstreetmap.org.

## Avec la vraie position du téléphone

Le téléphone envoie sa position GPS à l'application GPSd Forwarder, reçue par `gpsd` sur le PC
(ou plus tard sur la carte du casque) :

```bash
sudo apt install gpsd
sudo gpsd -N -n udp://0.0.0.0:29998        # même port que dans GPSd Forwarder
python smartguide_fonctionnel.py --position gpsd --carte carte_zone.json --destinations mes_lieux.json
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
| `osm.py` | télécharger la carte et en faire un plan |
| `itineraire.py` | plus court chemin (Dijkstra) |
| `guidage.py` | consignes pas à pas |
| `position.py` | position du téléphone (gpsd) ou marche simulée |
| `geo.py` | distances et caps |
