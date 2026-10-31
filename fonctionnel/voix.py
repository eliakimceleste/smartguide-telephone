"""Entrée et sortie vocales.

- Ecoute : enregistre le microphone pendant que l'on « appuie pour parler »
  (sur PC : Entrée pour commencer, Entrée pour finir).
- Transcripteur : Whisper (faster-whisper), en français, sur le processeur.
- Parole : gTTS (Google, Internet nécessaire) comme dans le mémoire, avec
  une voix hors ligne (pyttsx3 / eSpeak) en secours, ou du texte à l'écran.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading

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


class Transcripteur:
    """Whisper via faster-whisper. Le modèle est téléchargé au premier usage."""

    def __init__(self, modele="tiny", vocabulaire=()):
        from faster_whisper import WhisperModel

        self.modele = WhisperModel(modele, device="cpu", compute_type="int8")
        # Donner les noms des destinations aide Whisper à les reconnaître.
        self.indice = ("Commandes : aller à " + ", ".join(vocabulaire) + ". Oui. Non. Stop. Où suis-je ?"
                       if vocabulaire else None)

    def transcrit(self, audio):
        """`audio` : tableau numpy 16 kHz, ou chemin d'un fichier son."""
        segments, _ = self.modele.transcribe(audio, language="fr", beam_size=1,
                                             vad_filter=True, initial_prompt=self.indice)
        return " ".join(s.text.strip() for s in segments).strip()


class Parole:
    """Dit une phrase. mode : « gtts », « hors_ligne » ou « texte »."""

    def __init__(self, mode="gtts", dossier_cache=None):
        self.mode = mode
        self.cache = dossier_cache or os.path.join(tempfile.gettempdir(), "smartguide_voix")
        os.makedirs(self.cache, exist_ok=True)
        self._moteur = None

    def dit(self, texte):
        print(f"  SmartGuide : {texte}")
        if self.mode == "texte":
            return
        if self.mode == "gtts" and self._gtts(texte):
            return
        self._hors_ligne(texte)

    def _gtts(self, texte):
        """gTTS, avec un cache : une phrase déjà dite n'a plus besoin d'Internet."""
        fichier = os.path.join(self.cache, hashlib.sha1(texte.encode()).hexdigest() + ".mp3")
        if not os.path.exists(fichier):
            try:
                from gtts import gTTS
                gTTS(text=texte, lang="fr").save(fichier)
            except Exception:
                if os.path.exists(fichier):
                    os.remove(fichier)
                return False
        return _joue(fichier)

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
        if shutil.which("espeak-ng"):
            subprocess.run(["espeak-ng", "-v", "fr", texte], check=False)


def _joue(fichier):
    """Joue un mp3 avec le premier lecteur disponible."""
    for commande in (["mpg123", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
                     ["afplay"]):
        if shutil.which(commande[0]):
            return subprocess.run(commande + [fichier], check=False).returncode == 0
    try:
        from playsound import playsound
        playsound(fichier)
        return True
    except Exception:
        return False
