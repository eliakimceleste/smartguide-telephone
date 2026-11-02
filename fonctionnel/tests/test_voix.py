import os
import stat

import pytest

from voix import WhisperCpp


def _faux_whisper(dossier, sortie):
    """Un faux whisper-cli qui affiche `sortie` et vérifie qu'on lui demande le français."""
    os.makedirs(os.path.join(dossier, "build", "bin"))
    os.makedirs(os.path.join(dossier, "models"))
    open(os.path.join(dossier, "models", "ggml-tiny.bin"), "w").close()
    programme = os.path.join(dossier, "build", "bin", "whisper-cli")
    with open(programme, "w") as f:
        f.write("#!/bin/sh\ncase \"$*\" in *'-l fr'*) printf \"" + sortie + "\" ;; esac\n")
    os.chmod(programme, os.stat(programme).st_mode | stat.S_IEXEC)


def test_transcription_en_francais(tmp_path):
    _faux_whisper(str(tmp_path), " je veux aller\\n à la pharmacie\\n")
    whisper = WhisperCpp(str(tmp_path), "tiny", ["pharmacie"])
    assert whisper.transcrit("son.wav") == "je veux aller à la pharmacie"


def test_rien_enregistre(tmp_path):
    _faux_whisper(str(tmp_path), "texte")
    assert WhisperCpp(str(tmp_path), "tiny").transcrit(None) == ""


def test_modele_absent(tmp_path):
    _faux_whisper(str(tmp_path), "texte")
    with pytest.raises(FileNotFoundError, match="download-ggml-model.sh base"):
        WhisperCpp(str(tmp_path), "base")
