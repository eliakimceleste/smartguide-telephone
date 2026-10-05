# Reproduire le prototype du mémoire avec un téléphone

Le mémoire de A. DJIMA (IFRI 2022-2023) fait tourner sur un Raspberry Pi la chaîne suivante :
caméra → modèle SSD-MobileNetV2 (TFLite, COCO) → distance calculée avec la focale → voix gTTS qui annonce les objets à 100 cm ou moins.

Le code source et le modèle entraîné du mémoire (79 classes, 1338 photos de terrain) ne sont pas disponibles : seules des captures d'écran du code figurent en annexe. Les deux versions ci-dessous reprennent donc **le même algorithme et les mêmes constantes** (focale 852 × 180 / 50 = 3067,2 px, formule `50 × focale / (2 × largeur)`, seuil 100 cm, confiance 0,5), avec un modèle **pré-entraîné sur COCO** à la place du modèle fine-tuné.

## Le plus rapide : tester tout de suite sur le téléphone

Ouvrez cette page sur le téléphone, connecté au même compte Claude : https://claude.ai/artifact/XKFYtMTcXZWTi6ocfWiqyF

1. Appuyez sur **Prendre une photo** et choisissez « Appareil photo ».
2. Photographiez une chaise, une personne ou une table, à moins d'un mètre.
3. L'application encadre les objets, affiche leur distance et annonce l'objet le plus proche à voix haute (« une chaise à 85 centimètres »).

Cette page ne permet que des photos une par une : la vidéo en direct y est bloquée par sécurité. Pour la vidéo en direct, hébergez le dossier `application-telephone/` (partie A ci-dessous).

## Le code d'origine de l'autrice, avec le téléphone comme caméra

Dossier `script-original/` : c'est `TFLite_detection_webcam1.py` du dépôt SmartGuide, avec quatre petites retouches marquées `[reproduction]` (caméra du téléphone, pas de rotation, chemin du labelmap, espaces dans la phrase vocale). Le modèle fine-tuné n'étant pas publié, le dossier `Sample_TFLite_model/` contient le modèle COCO « starter » prévu par le code, avec un `labelmap_Fr.txt` en français.

```
pip install -r ../script-python/requirements.txt
python TFLite_detection_webcam1.py --modeldir Sample_TFLite_model --source http://IP-DU-TELEPHONE:8080/video --sans-rotation
```
Testé ici sur `test.mp4` du dépôt : la chaîne détection, distance et voix fonctionne. Attention, `test.mp4` est la vidéo de démonstration du tutoriel d'origine (une mangeoire à oiseaux), pas une scène de rue. Le script d'origine s'arrête avec une erreur à la fin d'une vidéo, ce qui est normal avec une caméra en direct.

| | A. Application téléphone (recommandée) | B. Script Python du mémoire |
|---|---|---|
| Où tourne la détection | Dans le navigateur du téléphone | Sur un ordinateur, le téléphone sert de caméra |
| Modèle | SSDLite MobileNetV2 COCO (TensorFlow.js) | SSD MobileNet COCO (TFLite, le « starter model » prévu par le code du mémoire) |
| Voix | Voix française du téléphone | gTTS comme dans le mémoire (voix du PC hors ligne en secours) |
| Fidélité au code d'origine | Même logique, réécrite en JavaScript | Même structure que l'annexe 3, presque ligne à ligne |
| Testé ici | Oui, photo de test : « une personne à 61 cm » | Oui, même photo : « une personne à 60 cm » |

---

## A. Application téléphone (Android ou iPhone)

Dossier : `application-telephone/` (aussi en `application-telephone.zip`). Tout est inclus (bibliothèques et modèle, 18 Mo) : après le premier chargement, rien n'est téléchargé depuis Internet.

### 1. Héberger le dossier en HTTPS
Le navigateur n'autorise la caméra que sur une adresse `https://`. Le plus simple :

1. Sur un ordinateur, ouvrez https://app.netlify.com/drop (compte gratuit).
2. Glissez le dossier `application-telephone` dans la page.
3. Netlify donne une adresse du type `https://nom-au-hasard.netlify.app`. Ouvrez-la sur le téléphone.

Autres possibilités : GitHub Pages (dépôt public, Settings → Pages), ou sur Android uniquement, un serveur local (`python -m http.server 8000` dans le dossier) puis, dans Chrome du téléphone, `chrome://flags` → « Insecure origins treated as secure » → ajouter `http://IP-DU-PC:8000`.

### 2. Utiliser
1. Branchez les écouteurs, montez le volume.
2. Appuyez sur **Démarrer** et acceptez l'accès à la caméra. Vous entendez « Guidage actif ».
3. Tenez le téléphone à hauteur de poitrine, caméra arrière vers l'avant (ou fixez-le sur une casquette comme dans le mémoire).
4. Approchez-vous d'une chaise ou d'une personne : sous 100 cm, la voix annonce « une chaise à 85 centimètres » et le téléphone vibre (Android).

Le bouton **Tester une photo** analyse une image de la galerie, utile pour vérifier que tout marche sans bouger.

### 3. Réglages
- **Seuil d'alerte** : 100 cm par défaut, comme dans le mémoire.
- **Calcul de distance** :
  - *Formule du mémoire* : reproduit exactement le code (largeur réelle fixe de 50 cm pour tous les objets, division par 2).
  - *Amélioré* : une largeur réelle par type d'objet (personne 45 cm, chaise 45 cm, voiture 180 cm…) et sans le facteur 2.
- **Calibrer la distance** : placez un objet à une distance mesurée, indiquez sa largeur et sa distance, appuyez sur *Calibrer*. C'est la même méthode que la photo de référence du mémoire (objet de 50 cm à 180 cm, 852 px de large).

---

## B. Script Python du mémoire, avec le téléphone comme caméra

Dossier : `script-python/`. Python 3.10 ou 3.11 conseillé.

1. Installer : `pip install -r requirements.txt`. Pour la voix gTTS il faut aussi **ffmpeg** (`sudo apt install ffmpeg`, ou le télécharger sous Windows). Sans Internet ou sans ffmpeg, le script bascule sur la voix du PC (pyttsx3).
2. Transformer le téléphone en caméra :
   - Android : appli **IP Webcam**, « Démarrer le serveur », noter l'adresse (ex. `http://192.168.1.20:8080`). Le téléphone et le PC doivent être sur le même Wi-Fi.
   - iPhone ou Android : **DroidCam** (appli + client PC), le téléphone apparaît alors comme webcam `0` ou `1`.
3. Lancer :
   ```
   python detection_telephone.py --modeldir coco --source http://192.168.1.20:8080/video
   python detection_telephone.py --modeldir coco --source 1          # DroidCam
   python detection_telephone.py --modeldir coco --image photo.jpg   # test sur une photo
   ```
   Options reprises du mémoire : `--threshold 0.5`, `--resolution 1280x720`, `--rotate` (image tournée de 180° comme sur le Pi). Nouvelle option : `--seuil 100` (distance d'alerte). Touche `q` pour quitter.
4. Si vous retrouvez le modèle entraîné du mémoire (`detect.tflite` + `labelmap.txt` + `labelmap_fr.txt`), mettez-le dans un dossier et passez-le avec `--modeldir` : le script détecte automatiquement un modèle TF2.

---

## Ce qu'il faut noter pour le mémoire (constats en reproduisant)

1. **La formule divise par 2.** Avec la photo de référence (852 px à 180 cm), la formule du code donne 90 cm, pas 180 cm. Toutes les distances du prototype sont donc environ deux fois trop courtes. Le mode *Amélioré* corrige ce point.
2. **Une seule largeur réelle (50 cm) pour tous les objets.** Une bouteille ou une voiture sont mal estimées. Une largeur par classe, ou une vraie mesure de profondeur, est une piste d'amélioration.
3. **Le seuil est décrit de deux façons dans le mémoire** : « au plus 100 cm » (p. 25) et « plus de 100 cm » (p. 39). La reproduction suit la page 25 et l'organigramme : seuls les objets à 100 cm ou moins sont annoncés.
4. **gTTS demande Internet** à chaque phrase et ajoute une latence. La version téléphone utilise la synthèse vocale intégrée, hors ligne et immédiate.
5. **Pas de suivi des alertes** dans le code d'origine : la même phrase peut se répéter à chaque image. La reproduction annonce l'objet le plus proche et attend 4 s avant de répéter le même objet.

## Pistes vers le casque avec navigation vocale
L'application téléphone est une bonne base pour la suite : on peut y ajouter la reconnaissance vocale (« je veux aller à la pharmacie »), le GPS et un itinéraire piéton, puis porter la caméra sur un casque relié au téléphone.
