"""Entrée et sortie vocales.

- Ecoute : enregistre le microphone pendant que l'on « appuie pour parler »
  (sur PC : Entrée pour commencer, Entrée pour finir).
- Transcripteur : Whisper (faster-whisper), en français, sur le processeur.
- Sur le téléphone (Termux) : micro d'Android enregistré, puis Whisper via
  whisper.cpp (WhisperCpp), en français et sans Internet.
- Parole : gTTS (Google, Internet nécessaire) comme dans le mémoire, avec
  une voix hors ligne (pyttsx3 / eSpeak) en secours, ou du texte à l'écran.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time

FREQUENCE = 16000  # Hz, ce qu'attend Whisper


class Ecoute:
    def __init__(self, duree_max=8.0):
        self.duree_max = duree_max

    def enregistre(self):
        """Renvoie le son (tableau numpy float32, 16 kHz mono)."""
        import numpy as np
        import sounddevice as sd

        input("  [Entrée] pour parler…")
        morceaux, fin = [], threading.Event()

        def rappel(donnees, _frames, _temps, _statut):
            morceaux.append(donnees.copy())

        print("  J'écoute… [Entrée] quand vous avez fini.")
        threading.Thread(target=lambda: (input(), fin.set()), daemon=True).start()
        with sd.InputStream(samplerate=FREQUENCE, channels=1, dtype="float32", callback=rappel):
            fin.wait(self.duree_max)
        if not morceaux:
            return np.zeros(0, dtype="float32")
        return np.concatenate(morceaux)[:, 0]


def enregistre_termux(dossier, duree_max=15):
    """Enregistre le micro du téléphone (`termux-microphone-record`) en
    « appuyer pour parler », puis le convertit en WAV 16 kHz mono pour Whisper."""
    os.makedirs(dossier, exist_ok=True)
    brut, wav = os.path.join(dossier, "ecoute.m4a"), os.path.join(dossier, "ecoute.wav")
    for f in (brut, wav):
        if os.path.exists(f):
            os.remove(f)
    input("  [Entrée] pour parler…")
    subprocess.run(["termux-microphone-record", "-f", brut, "-l", str(duree_max)], capture_output=True)
    input("  J'écoute… [Entrée] quand vous avez fini.")
    subprocess.run(["termux-microphone-record", "-q"], capture_output=True)
    # Android termine d'écrire le fichier juste après l'arrêt.
    taille = -1
    for _ in range(20):
        time.sleep(0.1)
        if os.path.exists(brut) and os.path.getsize(brut) == taille > 0:
            break
        taille = os.path.getsize(brut) if os.path.exists(brut) else -1
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", brut,
                    "-ar", str(FREQUENCE), "-ac", "1", "-c:a", "pcm_s16le", wav], check=False)
    return wav if os.path.exists(wav) else None


def _indice(vocabulaire):
    """Phrase donnée à Whisper pour l'aider à reconnaître les noms des destinations."""
    if not vocabulaire:
        return None
    return "Commandes : aller à " + ", ".join(vocabulaire) + ". Oui. Non. Stop. Où suis-je ?"


def ecoute_android():
    """Reconnaissance vocale d'Android (commande `termux-speech-to-text`).
    Attention : Termux:API la force en anglais (en-US), quels que soient les réglages."""
    input("  [Entrée] pour parler…")
    print("  J'écoute…")
    sortie = subprocess.run(["termux-speech-to-text"], capture_output=True, text=True).stdout
    lignes = [l.strip() for l in sortie.splitlines() if l.strip()]
    return lignes[-1] if lignes else ""


class Transcripteur:
    """Whisper via faster-whisper. Le modèle est téléchargé au premier usage."""

    def __init__(self, modele="tiny", vocabulaire=()):
        from faster_whisper import WhisperModel

        self.modele = WhisperModel(modele, device="cpu", compute_type="int8")
        self.indice = _indice(vocabulaire)

    def transcrit(self, audio):
        """`audio` : tableau numpy 16 kHz, ou chemin d'un fichier son."""
        segments, _ = self.modele.transcribe(audio, language="fr", beam_size=1,
                                             vad_filter=True, initial_prompt=self.indice)
        return " ".join(s.text.strip() for s in segments).strip()


class WhisperCpp:
    """Whisper sur le téléphone, via whisper.cpp compilé dans Termux.

    `dossier` : le dossier de whisper.cpp ; `modele` : tiny, base, small…
    (fichier models/ggml-<modele>.bin, téléchargé avec models/download-ggml-model.sh).
    """

    def __init__(self, dossier, modele="tiny", vocabulaire=()):
        self.programme = os.path.join(dossier, "build", "bin", "whisper-cli")
        self.modele = os.path.join(dossier, "models", f"ggml-{modele}.bin")
        for fichier, aide in ((self.programme, "compiler whisper.cpp (voir le README)"),
                              (self.modele, f"télécharger le modèle : sh models/download-ggml-model.sh {modele}")):
            if not os.path.exists(fichier):
                raise FileNotFoundError(f"{fichier} introuvable : {aide}")
        self.indice = _indice(vocabulaire)
        self.duree = 0.0  # secondes prises par la dernière transcription

    def transcrit(self, wav):
        if wav is None:
            return ""
        commande = [self.programme, "-m", self.modele, "-f", wav, "-l", "fr", "-nt", "-np",
                    "-t", str(os.cpu_count() or 4)]
        if self.indice:
            commande += ["--prompt", self.indice]
        debut = time.monotonic()
        sortie = subprocess.run(commande, capture_output=True, text=True).stdout
        self.duree = time.monotonic() - debut
        return " ".join(l.strip() for l in sortie.splitlines() if l.strip())


class Parole:
    """Dit une phrase. mode : « gtts », « android », « hors_ligne », « texte » ou « fichier »
    (phrases gTTS enregistrées en mp3 dans `sortie`, pour un serveur sans haut-parleur)."""

    def __init__(self, mode="gtts", dossier_cache=None, sortie="voix_sortie"):
        self.mode = mode
        self.sortie = os.path.abspath(sortie)
        self.numero = 0
        self.cache = dossier_cache or os.path.join(tempfile.gettempdir(), "smartguide_voix")
        os.makedirs(self.cache, exist_ok=True)
        self._moteur = None
        self._verrou = threading.Lock()
        self._en_attente = None    # phrases qui attendent d'être dites en fond
        self._fil = None
        self._android = None       # termux-tts-speak gardé ouvert pendant le guidage

    def dit(self, texte):
        """Dit la phrase et attend la fin (après les phrases dites en fond)."""
        self.attend()
        self._dit(texte)

    def dit_en_fond(self, phrases):
        """Dit les phrases sans attendre : le guidage continue de lire le GPS
        pendant qu'elles sont fabriquées et jouées. Si des phrases attendent
        encore leur tour, les nouvelles les remplacent : elles correspondent
        à une position plus récente."""
        if self.mode == "android" and shutil.which("termux-tts-speak"):
            self._android_en_fond(phrases)
            return
        with self._verrou:
            self._en_attente = list(phrases)
            if self._fil is None:
                self._fil = threading.Thread(target=self._parle_en_fond, daemon=True)
                self._fil.start()

    def _android_en_fond(self, phrases):
        """Voix d'Android pendant le guidage. Lancé sans texte, termux-tts-speak
        lit les phrases une par ligne et les dit au fur et à mesure : on le
        garde ouvert, le moteur de voix n'est créé qu'une fois et chaque
        consigne est dite aussitôt (au lieu de recréer le moteur à chaque
        phrase, ce qui prend plusieurs secondes)."""
        for texte in phrases:
            print(f"  SmartGuide : {texte}")
            ligne = " ".join(texte.split()) + "\n"
            for essai in range(2):
                if self._android is None or self._android.poll() is not None:
                    self._android = subprocess.Popen(
                        ["termux-tts-speak", "-l", "fr"], stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        text=True, encoding="utf-8")
                try:
                    self._android.stdin.write(ligne)
                    self._android.stdin.flush()
                    break
                except OSError:  # voix fermée entre-temps : la rouvrir
                    self._android = None

    def _ferme_android(self):
        """Fin du guidage : ferme la voix d'Android et attend qu'elle ait dit
        toutes les phrases reçues."""
        processus, self._android = self._android, None
        if processus is None:
            return
        try:
            processus.stdin.close()
        except OSError:
            pass
        try:
            processus.wait(timeout=60)
        except subprocess.TimeoutExpired:
            processus.kill()

    def attend(self):
        """Attend que les phrases dites en fond soient finies."""
        self._ferme_android()
        while True:
            with self._verrou:
                fil = self._fil
            if fil is None:
                return
            fil.join()

    def _parle_en_fond(self):
        while True:
            with self._verrou:
                phrases, self._en_attente = self._en_attente, None
                if not phrases:
                    self._fil = None
                    return
            for texte in phrases:
                self._dit(texte)

    def _dit(self, texte):
        print(f"  SmartGuide : {texte}")
        if self.mode == "texte":
            return
        if self.mode == "fichier":
            self._fichier(texte)
            return
        if self.mode == "android" and shutil.which("termux-tts-speak"):
            # voix d'Android (Termux) : sans Internet, elle parle tout de suite
            subprocess.run(["termux-tts-speak", "-l", "fr", texte], check=False)
            return
        if self.mode == "gtts" and self._gtts(texte):
            return
        self._hors_ligne(texte)

    def _fichier(self, texte):
        source = self._mp3(texte)
        if source is None:
            print("  (gTTS injoignable : vérifier la connexion Internet)")
            return
        os.makedirs(self.sortie, exist_ok=True)
        self.numero += 1
        cible = os.path.join(self.sortie, f"{self.numero:03d}.mp3")
        shutil.copyfile(source, cible)
        print(f"  (voix : {cible})")

    def _gtts(self, texte):
        fichier = self._mp3(texte)
        return fichier is not None and _joue(fichier)

    def _mp3(self, texte):
        """gTTS, avec un cache : une phrase déjà dite n'a plus besoin d'Internet."""
        fichier = os.path.join(self.cache, hashlib.sha1(texte.encode()).hexdigest() + ".mp3")
        if not os.path.exists(fichier):
            try:
                from gtts import gTTS
                gTTS(text=texte, lang="fr").save(fichier)
            except Exception:
                if os.path.exists(fichier):
                    os.remove(fichier)
                return None
        return fichier

    def _hors_ligne(self, texte):
        try:
            import pyttsx3
            if self._moteur is None:
                self._moteur = pyttsx3.init()
                for voix in self._moteur.getProperty("voices"):
                    if "fr" in (voix.id + str(getattr(voix, "languages", ""))).lower():
                        self._moteur.setProperty("voice", voix.id)
                        break
            self._moteur.say(texte)
            self._moteur.runAndWait()
            return
        except Exception:
            pass
        if shutil.which("termux-tts-speak"):  # voix d'Android, dans Termux
            subprocess.run(["termux-tts-speak", "-l", "fr", texte], check=False)
        elif shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", "-v", "fr", texte], check=False)


def _joue(fichier):
    """Joue un mp3 avec le premier lecteur disponible."""
    for commande in (["mpg123", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
                     ["mpv", "--no-video", "--really-quiet"], ["afplay"]):
        if shutil.which(commande[0]):
            return subprocess.run(commande + [fichier], check=False).returncode == 0
    try:
        from playsound import playsound
        playsound(fichier)
        return True
    except Exception:
        return False
