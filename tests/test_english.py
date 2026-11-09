"""Pin the repository to English: no German text outside the operator's quoted trigger phrases."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORDS = (
    "und", "nicht", "oder", "wird", "werden", "wurde", "kein", "keine", "keinen", "eine", "einen", "einem", "einer",
    "ist", "sind", "auf", "für", "bitte", "noch", "schon", "alle", "aus", "zum", "zur", "bei", "beim", "nach", "über",
    "dieser", "diese", "dieses", "jetzt", "heißt", "sich", "auch", "wenn", "dann", "mehr", "kann", "muss", "soll",
    "gibt", "ohne", "vom", "von", "läuft", "wählen", "speichern", "löschen", "abbrechen", "schließen", "bearbeiten",
    "anzeigen", "öffnen", "zeigen", "aufnehmen", "vorlesen", "regeln", "regel", "regelwunsch", "steuerung",
    "ausführen", "ressourcen", "hierarchie", "freigabe", "freigeben", "ablehnen", "warten", "wartet", "offen",
    "erledigt", "neu", "neuer", "angenommen", "abgelehnt", "gestoppt", "abgelaufen", "unbekannt",
    "fehlgeschlagen", "verweigert", "besetzt", "abberufen", "aufgabe", "aufgaben", "entfernt", "entfernen", "gemergt",
    "bleibt", "stoppt", "erzwingt", "verwirft", "hintergrund", "kategorien", "ansicht", "quelle", "namen", "suchen",
    "anheften", "entscheiden", "entscheidungen", "nacht", "abend", "himmel", "sonnenuntergang", "sonnenaufgang",
    "aufnahme", "nachricht", "nachrichten", "einstellungen", "sprache", "stumm", "fertig", "fehler", "gesperrt",
    "signiert", "heute", "gestern", "stunden", "minuten", "sekunden", "warnung", "hinweis", "sofort", "zeit",
    "weiter", "kopieren", "kopiert", "starten", "gestartet", "beenden", "beendet",
)
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(?:" + "|".join(WORDS) + r")\b", re.IGNORECASE)
ALLOWED = (
    '"rechtlich prüfen"', '"lizenz prüfen"', '"aufräumen"', '"branches aufräumen"', '"worktrees aufräumen"',
    '"was soll ich tun"', '"was muss ich tun"', '"was fehlt noch"', '"welche skills gibt es"', '"skill übersicht"',
    '"übersicht"', '"zuständigkeiten"', '"verwaiste branches"', '"alte worktrees"', '"was kann weg"', '"ä"',
    "(Regeln → Firewall, Hierarchie → Hierarchy, Ressourcen → Resources,", "Steuerung → Controls, Ausführen → Run)",
)
SELF = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()


def german_lines() -> list[str]:
    """Returns:
        Every `path:line` of a tracked text file that carries German once the
        allowed trigger phrases are removed from it.
    """
    files = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for name in files:
        if name == SELF:
            continue
        try:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for phrase in ALLOWED:
                line = line.replace(phrase, "")
            if GERMAN.search(line):
                hits.append(f"{name}:{number}")
    return hits


class TestEnglish(unittest.TestCase):
    def test_no_german_outside_quoted_trigger_phrases(self):
        self.assertEqual(german_lines(), [])


if __name__ == "__main__":
    print("\n".join(german_lines()))
