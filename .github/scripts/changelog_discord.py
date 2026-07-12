#!/usr/bin/env python3
"""Postet neue CHANGELOG.md-Abschnitte in den Discord-Changelog-Channel.

Läuft im GitHub-Actions-Workflow ``changelog-discord.yml`` nach jedem Push
auf main, der CHANGELOG.md ändert. Ermittelt aus dem Push-Diff
(``BEFORE..AFTER``) die NEU hinzugekommenen Versions-Abschnitte und postet
jeden einzeln (älteste zuerst) an den Webhook aus ``DISCORD_CHANGELOG_WEBHOOK``.

Bewusst nur Stdlib (kein pip auf dem Runner nötig). Fehlt das Secret,
beendet sich das Script mit Exit 0 — der Workflow bleibt grün, bis das
Secret gesetzt ist.

ENV:
  WEBHOOK      – Discord-Webhook-URL (leer → No-op)
  BEFORE/AFTER – Commit-Range des Pushes (BEFORE darf 000… sein → Fallback:
                 nur der neueste Abschnitt, z.B. bei workflow_dispatch)
  REPO_LABEL   – Anzeigename, z.B. "schach-bot" (Default)
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

CHANGELOG = 'CHANGELOG.md'
_SECTION_RE = re.compile(r'^## \[(?P<version>[^\]]+)\] - (?P<date>\S+)', re.MULTILINE)
_DISCORD_LIMIT = 2000
_TRUNCATE_AT = 1900  # Puffer für Header/Ellipse unterm 2000er-Limit
# SUPPRESS_NOTIFICATIONS ("silent message"): Post erscheint im Channel,
# löst aber bei niemandem Push-/Desktop-Benachrichtigungen aus.
_SILENT_FLAG = 4096


def parse_sections(text: str) -> dict[str, tuple[str, str]]:
    """CHANGELOG.md → {version: (date, body)}; body ohne die ##-Kopfzeile."""
    sections: dict[str, tuple[str, str]] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[m.group('version')] = (m.group('date'), text[start:end].strip())
    return sections


def added_versions(diff_text: str) -> list[str]:
    """Im Push-Diff NEU hinzugefügte Versions-Header, älteste zuerst."""
    versions = [m.group('version')
                for line in diff_text.splitlines()
                if line.startswith('+## [')
                and (m := _SECTION_RE.match(line[1:]))]
    return list(reversed(versions))  # Changelog ist neueste-zuerst → chronologisch drehen


def build_message(label: str, version: str, date: str, body: str) -> str:
    msg = f'**{label} v{version}** ({date})\n{body}'
    if len(msg) > _DISCORD_LIMIT:
        msg = msg[:_TRUNCATE_AT].rstrip() + ' …'
    return msg


def _post(webhook: str, content: str) -> None:
    payload = {'content': content, 'flags': _SILENT_FLAG}
    req = urllib.request.Request(
        webhook, data=json.dumps(payload).encode('utf-8'),
        # Expliziter User-Agent: Discords Cloudflare blockt Pythons
        # urllib-Default-UA mit 403 (error code 1010).
        headers={'Content-Type': 'application/json',
                 'User-Agent': 'schach-bot-changelog-webhook/1.0'}, method='POST')
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def main() -> int:
    webhook = os.environ.get('WEBHOOK', '').strip()
    if not webhook:
        print('DISCORD_CHANGELOG_WEBHOOK nicht gesetzt — überspringe Announce.')
        return 0

    label = os.environ.get('REPO_LABEL', 'schach-bot')
    before = os.environ.get('BEFORE', '')
    after = os.environ.get('AFTER', 'HEAD')

    with open(CHANGELOG, encoding='utf-8') as f:
        sections = parse_sections(f.read())
    if not sections:
        print('Keine Changelog-Abschnitte gefunden.')
        return 0

    versions: list[str] = []
    if before and not set(before) <= {'0'}:
        try:
            diff = subprocess.run(
                ['git', 'diff', f'{before}..{after}', '--', CHANGELOG],
                capture_output=True, text=True, check=True).stdout
            versions = [v for v in added_versions(diff) if v in sections]
        except subprocess.CalledProcessError as e:
            print(f'git diff fehlgeschlagen ({e}) — Fallback auf neuesten Abschnitt.')
    if not versions:
        versions = [next(iter(sections))]  # neuester Abschnitt (Datei ist neueste-zuerst)

    for v in versions:
        date, body = sections[v]
        _post(webhook, build_message(label, v, date, body))
        print(f'Gepostet: {label} v{v}')
        time.sleep(1)  # Discord-Rate-Limit schonen
    return 0


if __name__ == '__main__':
    sys.exit(main())
