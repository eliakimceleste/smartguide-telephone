"""
SmartGuide sur Raspberry Pi : reproduction du prototype du mémoire
« Système d'autoguidage pour les malvoyants » (A. DJIMA, IFRI 2022-2023).

Même chaîne que le script d'origine (TFLite_detection_webcam1.py) :
  caméra -> modèle TFLite SSD -> distance par la focale -> annonce vocale des objets à <= 100 cm.

Différences avec le script d'origine, pour qu'il tourne sur un Pi récent et serve de base aux nouveautés :
  - caméra Pi lue avec picamera2 (Raspberry Pi OS Bookworm), webcam USB ou vidéo en secours ;
  - voix dans un fil séparé : la détection continue pendant que la voix parle ;
  - voix hors ligne (espeak-ng) si gTTS n'a pas Internet ;
  - on annonce l'objet le plus proche, sans répéter la même phrase en boucle ;
  - journal CSV des détections pour le chapitre résultats.

Chaque étape est une classe séparée (Camera, Detecteur, estimer_distance, Voix) :
c'est là qu'on branchera les nouveautés (commande vocale, guidage, capteur de distance…).

Exemples :
  python3 smartguide_pi.py                         # caméra Pi, réglages du mémoire
  python3 smartguide_pi.py --source 0              # webcam USB
  python3 smartguide_pi.py --source test.mp4 --voix aucune --max-images 100   # test sans matériel
"""
import argparse
import csv
import io
import os
import queue
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- arguments
parser = argparse.ArgumentParser(description='SmartGuide : détection d\'obstacles et alerte vocale')
parser.add_argument('--modeldir', default=os.path.join(ICI, 'model'), help='Dossier du modèle .tflite')
parser.add_argument('--graph', default='detect.tflite')
parser.add_argument('--labels', default='labelmap.txt')
parser.add_argument('--labels_fr', default='labelmap_Fr.txt')
parser.add_argument('--threshold', type=float, default=0.5, help='Confiance minimale (mémoire : 0.5)')
parser.add_argument('--resolution', default='1280x720', help='Résolution de la caméra (mémoire : 1280x720)')
parser.add_argument('--source', default='picamera', help="picamera, 0 (webcam USB), ou un fichier vidéo")
parser.add_argument('--rotation', type=int, default=0, choices=[0, 180],
                    help='Tourner l\'image (le mémoire tournait de 180° car la caméra était à l\'envers)')
parser.add_argument('--seuil', type=float, default=100, help="Distance d'alerte vocale en cm (mémoire : 100)")
parser.add_argument('--distance', default='memoire', choices=['memoire', 'ameliore'],
                    help='memoire = formule du code d\'origine ; ameliore = largeur réelle par objet, sans division par 2')
parser.add_argument('--voix', default='auto', choices=['auto', 'gtts', 'espeak', 'aucune'],
                    help='auto = gTTS si Internet, sinon espeak-ng')
parser.add_argument('--repetition', type=float, default=4, help='Secondes avant de répéter la même annonce')
parser.add_argument('--affichage', action='store_true', help='Afficher la vidéo (écran ou VNC)')
parser.add_argument('--journal', default='', help='Fichier CSV où enregistrer les détections')
parser.add_argument('--max-images', type=int, default=0, help='Arrêter après N images (tests)')
args = parser.parse_args()
resW, resH = (int(v) for v in args.resolution.split('x'))


# ---------------------------------------------------------------- caméra
class Camera:
    """Fournit des images BGR. picamera2 pour la caméra Pi (Bookworm), OpenCV sinon."""

    def __init__(self, source, largeur, hauteur):
        self.picam = None
        if source == 'picamera':
            try:
                from picamera2 import Picamera2
                self.picam = Picamera2()
                config = self.picam.create_video_configuration(main={'size': (largeur, hauteur), 'format': 'RGB888'})
                self.picam.configure(config)
                self.picam.start()
                time.sleep(1)
                return
            except Exception as e:
                print('Caméra Pi indisponible (%s), essai de la webcam 0' % e)
                source = '0'
        self.cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, largeur)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, hauteur)
        if not self.cap.isOpened():
            raise SystemExit("Impossible d'ouvrir la caméra : %s" % source)

    def lire(self):
        if self.picam is not None:
            return self.picam.capture_array()  # « RGB888 » de picamera2 = ordre BGR, comme OpenCV
        ok, image = self.cap.read()
        return image if ok else None

    def fermer(self):
        if self.picam is not None:
            self.picam.stop()
        else:
            self.cap.release()


# ---------------------------------------------------------------- détecteur
def charger_interpreteur(chemin):
    for module in ('ai_edge_litert.interpreter', 'tflite_runtime.interpreter', 'tensorflow.lite.python.interpreter'):
        try:
            return __import__(module, fromlist=['Interpreter']).Interpreter(model_path=chemin, num_threads=4)
        except ImportError:
            continue
    raise SystemExit('Aucun moteur TFLite trouvé : lancez install.sh')


def lire_labels(chemin):
    with open(chemin, encoding='utf-8') as f:
        labels = [ligne.strip() for ligne in f]
    return labels[1:] if labels and labels[0] == '???' else labels   # même correction que le mémoire


class Detecteur:
    """Modèle TFLite SSD (modèle COCO « starter », ou le modèle entraîné du mémoire s'il est retrouvé)."""

    def __init__(self, dossier, graphe, labels, labels_fr, seuil_confiance):
        self.interp = charger_interpreteur(os.path.join(dossier, graphe))
        self.interp.allocate_tensors()
        self.entree = self.interp.get_input_details()
        self.sorties = self.interp.get_output_details()
        self.h, self.w = self.entree[0]['shape'][1], self.entree[0]['shape'][2]
        self.flottant = self.entree[0]['dtype'] == np.float32
        if 'StatefulPartitionedCall' in self.sorties[0]['name']:   # modèle TF2 (celui du mémoire)
            self.i_boites, self.i_classes, self.i_scores = 1, 3, 0
        else:                                                       # modèle TF1 (COCO starter)
            self.i_boites, self.i_classes, self.i_scores = 0, 1, 2
        self.labels = lire_labels(os.path.join(dossier, labels))
        chemin_fr = os.path.join(dossier, labels_fr)
        self.labels_fr = lire_labels(chemin_fr) if os.path.exists(chemin_fr) else self.labels
        self.seuil = seuil_confiance

    def detecter(self, image):
        """Renvoie une liste de dict : classe (anglais), nom (français), score, boite (xmin, ymin, xmax, ymax)."""
        imH, imW = image.shape[:2]
        entree = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (self.w, self.h))[np.newaxis]
        if self.flottant:
            entree = (np.float32(entree) - 127.5) / 127.5
        self.interp.set_tensor(self.entree[0]['index'], entree)
        self.interp.invoke()
        boites = self.interp.get_tensor(self.sorties[self.i_boites]['index'])[0]
        classes = self.interp.get_tensor(self.sorties[self.i_classes]['index'])[0]
        scores = self.interp.get_tensor(self.sorties[self.i_scores]['index'])[0]
        resultats = []
        for b, c, s in zip(boites, classes, scores):
            if self.seuil < s <= 1.0 and int(c) < len(self.labels):
                ymin, xmin = int(max(1, b[0] * imH)), int(max(1, b[1] * imW))
                ymax, xmax = int(min(imH, b[2] * imH)), int(min(imW, b[3] * imW))
                resultats.append({'classe': self.labels[int(c)], 'nom': self.labels_fr[int(c)],
                                  'score': float(s), 'boite': (xmin, ymin, xmax, ymax)})
        return resultats


# ---------------------------------------------------------------- distance
# Constantes du mémoire (annexe 3) : objet de 50 cm photographié à 180 cm, 852 px de large dans une image de 1280 px
MEASURED_DISTANCE, REFERENCE_REAL_WIDTH, REFERENCE_WIDTH_IMAGE, LARGEUR_REF = 180, 50, 852, 1280
FOCAL_LENGTH = REFERENCE_WIDTH_IMAGE * MEASURED_DISTANCE / REFERENCE_REAL_WIDTH   # 3067,2 px

# Largeurs réelles typiques (cm) pour le mode « ameliore »
LARGEURS = {'person': 45, 'bicycle': 60, 'car': 180, 'motorcycle': 80, 'bus': 250, 'truck': 250,
            'traffic light': 35, 'fire hydrant': 30, 'stop sign': 75, 'bench': 150, 'dog': 25, 'cat': 15,
            'backpack': 30, 'suitcase': 45, 'chair': 45, 'couch': 200, 'potted plant': 40, 'bed': 150,
            'dining table': 120, 'toilet': 40, 'tv': 100, 'laptop': 34, 'bottle': 8, 'cup': 9,
            'refrigerator': 70, 'sink': 60}


def estimer_distance(objet, largeur_image, mode):
    xmin, _, xmax, _ = objet['boite']
    largeur_px = max(1, xmax - xmin) * LARGEUR_REF / largeur_image   # ramené à une image de 1280 px
    if mode == 'memoire':
        return REFERENCE_REAL_WIDTH * FOCAL_LENGTH / (2 * largeur_px)   # formule exacte du code d'origine
    return LARGEURS.get(objet['classe'], REFERENCE_REAL_WIDTH) * FOCAL_LENGTH / largeur_px


# ---------------------------------------------------------------- voix
class Voix:
    """Parle dans un fil séparé. Une seule phrase en attente : si la voix parle encore, l'alerte est ignorée."""

    def __init__(self, moteur):
        self.moteur = moteur
        self.file = queue.Queue(maxsize=1)
        self.cache_gtts = {}
        threading.Thread(target=self._boucle, daemon=True).start()

    def dire(self, texte):
        try:
            self.file.put_nowait(texte)
            return True
        except queue.Full:
            return False

    def _boucle(self):
        while True:
            texte = self.file.get()
            if self.moteur in ('auto', 'gtts') and self._gtts(texte):
                continue
            if self.moteur in ('auto', 'espeak'):
                self._espeak(texte)

    def _gtts(self, texte):
        """Comme le mémoire (annexe 4) : gTTS en français, lu ici avec mpg123."""
        if not shutil.which('mpg123'):
            return False
        try:
            if texte not in self.cache_gtts:
                from gtts import gTTS
                tampon = io.BytesIO()
                gTTS(text=texte, lang='fr').write_to_fp(tampon)
                self.cache_gtts[texte] = tampon.getvalue()
            subprocess.run(['mpg123', '-q', '-'], input=self.cache_gtts[texte], check=True, timeout=15)
            return True
        except Exception as e:
            print('gTTS indisponible (%s), voix hors ligne' % type(e).__name__)
            return False

    def _espeak(self, texte):
        if shutil.which('espeak-ng'):
            subprocess.run(['espeak-ng', '-v', 'fr', '-s', '160', texte], timeout=15)


def phrase(objet, distance):
    # Même tournure que le mémoire (« un <objet> à <distance> centimètres »), arrondie à 10 cm
    nom = objet['nom'] if objet['nom'].startswith(('un ', 'une ')) else 'un ' + objet['nom']
    return '%s à %d centimètres' % (nom, int(round(distance, -1)))


# ---------------------------------------------------------------- programme principal
def main():
    camera = Camera(args.source, resW, resH)
    detecteur = Detecteur(args.modeldir, args.graph, args.labels, args.labels_fr, args.threshold)
    voix = Voix(args.voix)
    journal = None
    if args.journal:
        nouveau = not os.path.exists(args.journal)
        fichier = open(args.journal, 'a', newline='', encoding='utf-8')
        journal = csv.writer(fichier)
        if nouveau:
            journal.writerow(['heure', 'objet', 'confiance', 'distance_cm', 'annonce'])

    if args.voix != 'aucune':
        voix.dire('Guidage actif')
    derniere = {'classe': None, 't': 0.0}
    n, t_fps, fps = 0, time.time(), 0.0
    try:
        while True:
            image = camera.lire()
            if image is None:
                print('Flux vidéo terminé')
                break
            if args.rotation == 180:
                image = cv2.rotate(image, cv2.ROTATE_180)

            objets = detecteur.detecter(image)
            for o in objets:
                o['distance'] = estimer_distance(o, image.shape[1], args.distance)

            proches = sorted((o for o in objets if o['distance'] <= args.seuil), key=lambda o: o['distance'])
            annonce = ''
            if proches:
                o = proches[0]
                maintenant = time.time()
                if o['classe'] != derniere['classe'] or maintenant - derniere['t'] > args.repetition:
                    annonce = phrase(o, o['distance'])
                    if args.voix == 'aucune' or voix.dire(annonce):
                        print('ALERTE :', annonce)
                        derniere = {'classe': o['classe'], 't': maintenant}
                    else:
                        annonce = ''

            if journal:
                heure = time.strftime('%H:%M:%S')
                for o in objets:
                    journal.writerow([heure, o['nom'], '%.2f' % o['score'], int(o['distance']),
                                      annonce if proches and o is proches[0] else ''])

            if args.affichage:
                for o in objets:
                    xmin, ymin, xmax, ymax = o['boite']
                    couleur = (78, 90, 255) if o['distance'] <= args.seuil else (63, 210, 255)
                    cv2.rectangle(image, (xmin, ymin), (xmax, ymax), couleur, 2)
                    cv2.putText(image, '%s %d%% %dcm' % (o['nom'], o['score'] * 100, o['distance']),
                                (xmin, max(20, ymin - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, couleur, 2)
                cv2.putText(image, '%.1f img/s' % fps, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
                cv2.imshow('SmartGuide', image)
                if cv2.waitKey(1) == ord('q'):
                    break

            n += 1
            if n % 20 == 0:
                fps = 20 / (time.time() - t_fps)
                t_fps = time.time()
                print('%.1f images/s' % fps)
            if args.max_images and n >= args.max_images:
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.fermer()
        if args.affichage:
            cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
