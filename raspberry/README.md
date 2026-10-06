# SmartGuide sur Raspberry Pi : reproduire le prototype physique

Ce dossier reproduit le casque du mémoire (chapeau + caméra + Raspberry Pi + écouteurs) avec le même algorithme que le code d'origine : détection d'objets TFLite, distance par la focale, annonce vocale des objets à 100 cm ou moins.

## 1. Matériel

| Élément | Choix conseillé | Dans le mémoire |
|---|---|---|
| Carte | Raspberry Pi 4 (4 ou 8 Go) ou Pi 5 | Pi 4, 8 Go (le tableau dit « Pi 3 » par erreur) |
| Stockage | microSD 32 Go, classe A1/A2 | microSD |
| Caméra | Module caméra Pi v1.3, v2 ou v3 + nappe adaptée (Pi 5 : nappe 22→15 broches) | Caméra Pi v1.3, 5 MP |
| Son | Écouteurs filaires jack 3,5 mm (Pi 4) ; USB ou Bluetooth sur Pi 5 | Écouteurs sur la sortie audio |
| Alimentation | Batterie externe USB-C 5 V / 3 A, ~10 000 mAh | Batterie |
| Interrupteur | Bouton-poussoir + 2 câbles jumper femelle | Interrupteur relié par jumper |
| Support | Casquette ou chapeau, supports imprimés en PLA | Chapeau, supports en PLA |
| Optionnel | ESP32 DevKit v1 (pour un futur capteur de distance) | ESP32 relié en Wi-Fi |

## 2. Préparer la carte SD
1. Sur un ordinateur, installez **Raspberry Pi Imager**.
2. Choisissez **Raspberry Pi OS (64-bit)**, la version Bookworm actuelle.
3. Dans les réglages (roue dentée) : nom d'utilisateur, Wi-Fi, et **activer SSH**.
4. Insérez la carte dans le Pi, branchez la caméra (Pi éteint, côté contacts de la nappe vers le connecteur), allumez.

## 3. Installer SmartGuide
Connectez-vous en SSH (`ssh utilisateur@nom-du-pi.local`) puis :
```
git clone https://github.com/eliakimceleste/smartguide-telephone
cd smartguide-telephone/raspberry
bash install.sh
```
Le script installe la caméra, OpenCV, la voix (gTTS + espeak-ng hors ligne), le moteur TFLite, puis vérifie que le modèle se charge et que la voix sort. Si vous n'entendez rien : `sudo raspi-config` → *System Options* → *Audio* → sortie jack.

## 4. Premier test
```
rpicam-hello -t 5000                                   # la caméra fonctionne ?
./venv/bin/python smartguide_pi.py --affichage         # avec un écran ou VNC : vidéo + boîtes
./venv/bin/python smartguide_pi.py                     # sans écran : seulement la voix
```
Placez une chaise à moins d'un mètre : vous devez entendre « une chaise à 80 centimètres ».

Options utiles :
- `--rotation 180` si la caméra est montée à l'envers (c'était le cas dans le mémoire) ;
- `--seuil 150` pour annoncer les objets jusqu'à 150 cm ;
- `--distance ameliore` pour une distance plus réaliste (largeur réelle par type d'objet, sans la division par 2 du code d'origine) ;
- `--voix espeak` pour forcer la voix hors ligne (plus rapide que gTTS, ne demande pas Internet) ;
- `--journal essais.csv` pour enregistrer chaque détection (heure, objet, confiance, distance) ;
- `--source 0` pour une webcam USB à la place de la caméra Pi.

## 5. Démarrage automatique (comme le crontab du mémoire)
```
mkdir -p ~/.config/systemd/user
cp smartguide.service ~/.config/systemd/user/
systemctl --user enable --now smartguide
sudo loginctl enable-linger $USER
```
SmartGuide démarre alors à chaque allumage, sans écran ni clavier, et dit « Guidage actif ». Pour voir ce qu'il fait : `journalctl --user -u smartguide -f`. Pour l'arrêter : `systemctl --user stop smartguide`.

## 6. Bouton marche/arrêt
Le Pi n'a pas d'interrupteur ; on en ajoute un sans programme :
1. Reliez un bouton-poussoir entre la **broche 5 (GPIO 3)** et la **broche 6 (GND)**.
2. Ajoutez à la fin de `/boot/firmware/config.txt` la ligne `dtoverlay=gpio-shutdown`, puis redémarrez.

Un appui éteint proprement le Pi ; un nouvel appui le rallume (sur Pi 4 et Pi 5, tant que la batterie reste branchée). Sur Pi 5, le bouton d'alimentation intégré fait la même chose.

## 7. Montage sur le chapeau
- Caméra à l'avant, au centre, légèrement inclinée vers le bas pour voir le sol à 1-2 m.
- Pi et batterie à l'arrière ou sur le dessus pour équilibrer le poids ; laissez de l'air autour du Pi (il chauffe pendant la détection, un petit dissipateur est conseillé).
- Notez la hauteur de la caméra et son inclinaison : elles comptent pour la distance et pour votre chapitre résultats.

## 8. Calibrer la distance
La formule d'origine utilise une photo de référence : objet de 50 cm à 180 cm, 852 px de large dans une image de 1280 px. Avec votre caméra :
1. Placez un objet de largeur connue (ex. une planche de 50 cm) à 180 cm.
2. Lancez `./venv/bin/python smartguide_pi.py --affichage` et lisez la largeur de sa boîte (xmax − xmin) ou mesurez-la sur une capture.
3. Remplacez `REFERENCE_WIDTH_IMAGE = 852` dans `smartguide_pi.py` par votre valeur.

## Où greffer les nouveautés
Le script est découpé pour ça :
- `Camera` : autre caméra, caméra stéréo ;
- `Detecteur` : votre propre modèle entraîné (même format TFLite + `labelmap.txt` + `labelmap_Fr.txt`, avec « un » ou « une » devant chaque nom) ;
- `estimer_distance` : capteur à ultrasons ou ToF (via l'ESP32), ou estimation de profondeur ;
- `Voix` : autre voix (Piper), messages de guidage ;
- la boucle `main()` : commandes vocales (« je veux aller à… ») et itinéraire, dans un fil séparé comme la voix.
