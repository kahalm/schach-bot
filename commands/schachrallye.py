"""Schachrallye + Turnier-Verwaltung: Termine von tirol.chess.at importieren.

Alle Termine landen in einer einzigen turnier.json mit Tags.
Tag 'schachrallye' kennzeichnet Rallye-Termine (mit Reminder + Subscriber).

/schachrallye       — Rallye-Termine anzeigen
/schachrallye_add   — Manuell Rallye-Termin anlegen (Admin)
/schachrallye_del   — Rallye-Termin loeschen (Admin)
/schachrallye_sub   — Fuer Rallye-Erinnerungen subscriben
/schachrallye_unsub — Rallye-Erinnerungen abbestellen
/turnier_parse — Termine von tirol.chess.at importieren (Admin)
/turnier            — Alle zukuenftigen Turniere anzeigen
/turnier_sub <tag>  — Fuer Tag subscriben (Ping bei neuen Turnieren)
/turnier_unsub <tag>— Tag-Abo abbestellen
"""

import asyncio
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser

import discord
import requests
from discord.ext import tasks

from urllib.parse import urlparse

from core.datetime_utils import parse_datum as _parse_datum
from core.json_store import atomic_read, atomic_update
from core.paths import CONFIG_DIR
from core.permissions import is_privileged
from core.version import EMBED_COLOR

log = logging.getLogger('schach-bot')


def _is_valid_url(url: str) -> bool:
    """Prueft ob ein String eine gueltige http/https URL ist."""
    try:
        p = urlparse(url)
        return (p.scheme in ('http', 'https')
                and '.' in p.netloc
                and ' ' not in url)
    except Exception:
        return False


TURNIER_FILE = os.path.join(CONFIG_DIR, 'turnier.json')
RALLYE_URL = 'https://tirol.chess.at/termine/'
def _fresh_default():
    """Frisches Default-Dict (Deep Copy) — vermeidet Shared-State durch shallow copy."""
    return {"events": [], "subscribers": {}, "reviewers": [], "next_id": 1}

_PRUNE_DAYS = 90  # Alte Events nach N Tagen entfernen

_bot = None
_tournament_channel_id = 0


def _prune_old_events():
    """Entfernt Events die aelter als _PRUNE_DAYS Tage sind."""
    cutoff = date.today() - timedelta(days=_PRUNE_DAYS)
    pruned = [0]

    def _prune(data):
        before = len(data.get('events', []))
        data['events'] = [
            e for e in data.get('events', [])
            if (_parse_stored(e.get('datum', '')) or date.min) >= cutoff
        ]
        pruned[0] = before - len(data['events'])
        return data

    atomic_update(TURNIER_FILE, _prune, default=_fresh_default)
    if pruned[0]:
        log.info('Turnier-Prune: %d alte Events entfernt (> %d Tage).', pruned[0], _PRUNE_DAYS)


def _parse_stored(text: str) -> date | None:
    """Parst gespeichertes YYYY-MM-DD zu date."""
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def _parse_datum_flex(text: str) -> tuple[date | None, str]:
    """Parst Datum oder Datumsbereich, gibt (start_date, display_text) zurueck.

    Unterstuetzte Formate:
      14.05.2026          → einfaches Datum
      20.-24.05.2026      → Bereich, gleicher Monat
      22.05.-25.05.2026   → Bereich, verschiedene Monate
      03.06.-07.06.2026   → Bereich, verschiedene Monate
      20. + 21.06.2026    → Zwei Tage
      31.07.-02.08.2026   → Bereich ueber Monatswechsel
    """
    text = text.strip()
    d = _parse_datum(text)
    if d:
        return d, text

    # "20.-24.05.2026" oder "20. + 21.06.2026"
    m = re.match(r'(\d{1,2})\.\s*[-+]\s*\d{1,2}\.(\d{2}\.\d{4})', text)
    if m:
        return _parse_datum(f'{m.group(1)}.{m.group(2)}'), text

    # "22.05.-25.05.2026" oder "03.06.-07.06.2026"
    m = re.match(r'(\d{1,2}\.\d{2}\.)\s*-\s*\d{1,2}\.\d{2}\.(\d{4})', text)
    if m:
        return _parse_datum(f'{m.group(1)}{m.group(2)}'), text

    return None, text


def _shorten_ort(ort: str) -> str:
    """Kuerzt lange Ort-Beschreibungen auf den wesentlichen Teil."""
    if not ort:
        return ''
    for sep in [',', ';', '(', 'Info ', 'Meldung', 'Anmeldung']:
        idx = ort.find(sep)
        if 0 < idx < 60:
            ort = ort[:idx].strip()
            break
    if len(ort) > 60:
        ort = ort[:59].strip() + '\u2026'
    return ort


def _format_turnier_line(e: dict) -> str:
    """Formatiert einen Turnier-Eintrag als einzeiligen Markdown-String."""
    dt = e.get('datum_text', '')
    if not dt:
        d = _parse_stored(e['datum'])
        dt = d.strftime('%d.%m.%Y') if d else e['datum']
    link = e.get('link', '')
    name = e['name']
    ort = _shorten_ort(e.get('ort', ''))

    if link and _is_valid_url(link):
        line = f"`{dt}` [**{name}**]({link})"
    else:
        line = f"`{dt}` **{name}**"
    if ort:
        line += f" \u00b7 {ort}"
    return line


# ---------------------------------------------------------------------------
# HTML-Parser fuer tirol.chess.at/termine/
# ---------------------------------------------------------------------------

class _TerminParser(HTMLParser):
    """Extrahiert Tabellenzeilen + Links aus der Termin-Seite."""

    def __init__(self):
        super().__init__()
        self._in_table = False
        self._in_td = False
        self._in_th = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._current_links: list[str] = []
        self._row_links: list[list[str]] = []
        self.rows: list[list[str]] = []
        self.row_links: list[list[list[str]]] = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self._in_table = True
        elif tag == 'td' and self._in_table:
            self._in_td = True
            self._current_cell = []
            self._current_links = []
        elif tag == 'th' and self._in_table:
            self._in_th = True
        elif tag == 'tr' and self._in_table:
            self._current_row = []
            self._row_links = []
        elif tag == 'br' and self._in_td:
            self._current_cell.append(' ')
        elif tag == 'a' and self._in_td:
            # Space vor Link-Text einfuegen, damit "NameAusschreibung" → "Name Ausschreibung"
            if self._current_cell:
                self._current_cell.append(' ')
            href = dict(attrs).get('href', '')
            if href:
                self._current_links.append(href)

    def handle_endtag(self, tag):
        if tag == 'table':
            self._in_table = False
        elif tag == 'td' and self._in_td:
            self._in_td = False
            self._current_row.append(' '.join(''.join(self._current_cell).split()))
            self._row_links.append(list(self._current_links))
        elif tag == 'th':
            self._in_th = False
        elif tag == 'tr' and self._in_table:
            if self._current_row:
                self.rows.append(self._current_row)
                self.row_links.append(list(self._row_links))

    def handle_data(self, data):
        if self._in_td:
            self._current_cell.append(data)


def _fetch_termine() -> list[dict]:
    """Fetcht tirol.chess.at/termine/ und gibt Termine mit Tags zurueck.

    Returns: Liste von Event-Dicts mit keys: datum, datum_text, name, ort, link, tags.
    """
    from core.version import VERSION
    resp = requests.get(RALLYE_URL, timeout=15,
                        headers={'User-Agent': f'schach-bot/{VERSION}'})
    resp.raise_for_status()

    parser = _TerminParser()
    parser.feed(resp.text)

    events: list[dict] = []
    for row, links in zip(parser.rows, parser.row_links):
        if len(row) < 3:
            continue
        datum_text, name, ort = row[0].strip(), row[1].strip(), row[2].strip()
        name_lower = name.lower()
        # Training-Eintraege komplett ignorieren
        if 'training' in name_lower:
            continue
        # OeM U08/U10 und U12/U14 ignorieren
        if 'meisterschaften u' in name_lower:
            continue
        d, display = _parse_datum_flex(datum_text)
        if d is None:
            continue
        # Artefakte aus dem Namen entfernen
        for artifact in ['Ausschreibung', 'Anmeldung']:
            cleaned = name.replace(artifact, '').strip()
            if cleaned:
                name = cleaned
        # Zeitangaben entfernen ("Start: 10 Uhr", "10:00 Uhr Turnierbeginn")
        name = re.sub(r'\s*Start:\s*\d{1,2}(?::\d{2})?\s*Uhr\b', '', name).strip()
        name = re.sub(r'\s*\d{1,2}:\d{2}\s*Uhr\s*Turnierbeginn\b', '', name).strip()
        # "auf Chess-Results" entfernen
        name = re.sub(r'\s+auf Chess-Results\b', '', name).strip()
        # Link aus der Veranstaltungs-Spalte (Index 1) nehmen
        event_links = links[1] if len(links) > 1 else []
        link = event_links[0] if event_links else ''
        tags = []
        for keyword in ['schachrallye', 'rallye', 'schnellschach', 'blitz', '960']:
            if keyword in name_lower:
                tag = 'schachrallye' if keyword == 'rallye' else keyword
                if tag not in tags:
                    tags.append(tag)
        # Jugend-Tag: Jugend*, U08-U18 etc.
        if re.search(r'jugend|u\d{2}', name_lower):
            if 'jugend' not in tags:
                tags.append('jugend')
        # Senioren-Tag
        if 'senior' in name_lower:
            if 'senioren' not in tags:
                tags.append('senioren')
        # Klassisch-Tag (Open-Turniere)
        if 'open' in name_lower:
            if 'klassisch' not in tags:
                tags.append('klassisch')
        events.append({
            'datum': d.strftime('%Y-%m-%d'),
            'datum_text': display,
            'name': name,
            'ort': ort,
            'link': link,
            'tags': tags,
        })
    return events


# ---------------------------------------------------------------------------
# Post-Logik (Modul-Ebene, importiert von turnier_buttons.py)
# ---------------------------------------------------------------------------

async def _post_approved_event(event: dict):
    """Postet ein freigegebenes Event im Tournament-Channel mit Mentions."""
    if not _tournament_channel_id:
        return
    channel = _bot.get_channel(_tournament_channel_id)
    if not channel:
        return

    subs_data = atomic_read(TURNIER_FILE, default=dict).get('subscribers', {})
    dt = event.get('datum_text', event.get('datum', ''))
    ort = _shorten_ort(event.get('ort', ''))
    link = event.get('link', '')
    tags = event.get('tags', [])
    desc = f"\U0001f4c5 `{dt}`"
    if ort:
        desc += f" \u00b7 {ort}"
    if tags:
        desc += '\n' + ' '.join(f'`{t}`' for t in tags)
    # Subscriber-Mentions sammeln
    mention_ids = set()
    for t in tags:
        mention_ids.update(subs_data.get(t, []))
    mention_text = (' '.join(f'<@{uid}>' for uid in mention_ids)
                    if mention_ids else '')
    embed = discord.Embed(
        title=event.get('name', ''),
        description=desc,
        color=EMBED_COLOR,
    )
    if link and _is_valid_url(link):
        embed.url = link
    embed.set_footer(text='tirol.chess.at/termine/')
    try:
        await channel.send(content=mention_text or None, embed=embed)
    except Exception:
        log.exception('Turnier-Post fehlgeschlagen fuer %s', event.get('name', ''))


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup(bot, tournament_channel_id: int = 0):
    global _bot, _tournament_channel_id
    _bot = bot
    _tournament_channel_id = tournament_channel_id
    tree = bot.tree

    # turnier_buttons mit Bot-Referenz konfigurieren
    from commands.turnier_buttons import configure as _configure_buttons
    _configure_buttons(bot, tournament_channel_id)

    # --- /schachrallye -------------------------------------------------------

    @tree.command(name='schachrallye',
                  description='Alle zukuenftigen Schachrallye-Termine anzeigen')
    async def cmd_schachrallye(interaction: discord.Interaction):
        data = atomic_read(TURNIER_FILE, default=dict)
        if not data:
            data = _fresh_default()
        events = data.get('events', [])
        subs = data.get('subscribers', {}).get('schachrallye', [])

        today = date.today()
        future = [e for e in events
                  if 'schachrallye' in e.get('tags', [])
                  and (_parse_stored(e['datum']) or date.min) >= today]
        future.sort(key=lambda e: e['datum'])

        if not future:
            await interaction.response.send_message(
                'Keine anstehenden Schachrallye-Termine vorhanden.',
                ephemeral=True)
            return

        lines = []
        for e in future:
            d = _parse_stored(e['datum'])
            ts = int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc).timestamp())
            name = e.get('name', '')
            ort = _shorten_ort(e.get('ort', ''))
            if name:
                line = f"**#{e['id']}** \u2014 <t:{ts}:D> **{name}**"
            else:
                line = f"**#{e['id']}** \u2014 <t:{ts}:D>"
            if ort:
                line += f" \u00b7 {ort}"
            lines.append(line)

        desc = '\n'.join(lines)
        if subs:
            mentions = ', '.join(f'<@{uid}>' for uid in subs)
            desc += f'\n\n**Subscriber ({len(subs)}):** {mentions}'

        embed = discord.Embed(
            title='\U0001f3c7 Schachrallye \u2014 Termine',
            description=desc,
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name='schachrallye_add',
                  description='Neuen Schachrallye-Termin anlegen (Admin)')
    @discord.app_commands.describe(
        datum='Datum im Format TT.MM.JJJJ',
        ort='Ort des Turniers',
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_schachrallye_add(interaction: discord.Interaction,
                                   datum: str, ort: str):
        if not is_privileged(interaction):
            await interaction.response.send_message('⚠️ Nur für Admins.', ephemeral=True)
            return
        d = _parse_datum(datum)
        if d is None:
            await interaction.response.send_message(
                '\u26a0\ufe0f Ungueltiges Datum. Format: `TT.MM.JJJJ` (z.B. 15.05.2026)',
                ephemeral=True)
            return
        if d < date.today():
            await interaction.response.send_message(
                '\u26a0\ufe0f Das Datum liegt in der Vergangenheit.',
                ephemeral=True)
            return

        result = {}

        def _add(data):
            if not isinstance(data, dict) or 'events' not in data:
                data = _fresh_default()
            new_id = data.get('next_id', 1)
            data['events'].append({
                'id': new_id,
                'datum': d.strftime('%Y-%m-%d'),
                'datum_text': datum.strip(),
                'name': '',
                'ort': ort,
                'link': '',
                'tags': ['schachrallye'],
                'reminded': False,
            })
            data['next_id'] = new_id + 1
            result['id'] = new_id
            return data

        atomic_update(TURNIER_FILE, _add)
        ts = int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc).timestamp())
        await interaction.response.send_message(
            f"\u2705 Termin #{result['id']} angelegt: <t:{ts}:D> in **{ort}**",
            ephemeral=True)

    @tree.command(name='schachrallye_del',
                  description='Schachrallye-Termin loeschen (Admin)')
    @discord.app_commands.describe(id='ID des Termins (aus /schachrallye)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_schachrallye_del(interaction: discord.Interaction, id: int):
        if not is_privileged(interaction):
            await interaction.response.send_message('⚠️ Nur für Admins.', ephemeral=True)
            return
        result = {'found': False}

        def _del(data):
            if not isinstance(data, dict) or 'events' not in data:
                return data
            before = len(data['events'])
            data['events'] = [e for e in data['events'] if e['id'] != id]
            if len(data['events']) < before:
                result['found'] = True
            return data

        atomic_update(TURNIER_FILE, _del)
        if result['found']:
            await interaction.response.send_message(
                f'\u2705 Termin #{id} geloescht.', ephemeral=True)
        else:
            await interaction.response.send_message(
                f'\u274c Termin #{id} nicht gefunden.', ephemeral=True)

    @tree.command(name='schachrallye_sub',
                  description='Fuer Schachrallye-Erinnerungen subscriben')
    @discord.app_commands.describe(
        user='Anderen User subscriben (nur Admin)')
    async def cmd_schachrallye_sub(interaction: discord.Interaction,
                                   user: discord.User = None):
        if user and not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins koennen andere User subscriben.',
                ephemeral=True)
            return

        target = user or interaction.user
        result = {'already': False}

        def _sub(data):
            if not isinstance(data, dict) or 'subscribers' not in data:
                data = _fresh_default()
            subs = data['subscribers'].setdefault('schachrallye', [])
            if target.id in subs:
                result['already'] = True
                return data
            subs.append(target.id)
            return data

        atomic_update(TURNIER_FILE, _sub)
        if result['already']:
            name = f'**{target.display_name}**' if user else 'Du bist'
            suffix = 'ist bereits subscribed.' if user else 'bereits subscribed.'
            await interaction.response.send_message(
                f'{name} {suffix}', ephemeral=True)
        else:
            if user:
                await interaction.response.send_message(
                    f'\u2705 **{target.display_name}** fuer Schachrallye subscribed.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    '\u2705 Du bist jetzt fuer Schachrallye-Erinnerungen subscribed.\n'
                    'Du wirst bei neuen Rallye-Turnieren gepingt und 7 Tage vorher erinnert.',
                    ephemeral=True)
            # DM an den subscribten User
            try:
                dm = await target.create_dm()
                await dm.send(
                    'Du wurdest fuer die **Schachrallye-Erinnerungen** angemeldet!\n'
                    '\u2022 Bei neuen Rallye-Turnieren wirst du im Channel gepingt\n'
                    '\u2022 7 Tage vor jedem Termin bekommst du eine Erinnerung\n'
                    'Mit `/schachrallye` siehst du alle Termine. '
                    'Mit `/schachrallye_unsub` kannst du dich jederzeit abmelden.'
                )
            except discord.Forbidden:
                log.warning('Rallye-Sub-DM an %s nicht moeglich (DMs deaktiviert).', target.id)
            except Exception:
                log.warning('Rallye-Sub-DM an %s fehlgeschlagen.', target.id)

    @tree.command(name='schachrallye_unsub',
                  description='Schachrallye-Erinnerungen abbestellen')
    @discord.app_commands.describe(
        user='Anderen User unsubscriben (nur Admin)')
    async def cmd_schachrallye_unsub(interaction: discord.Interaction,
                                     user: discord.User = None):
        if user and not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins koennen andere User unsubscriben.',
                ephemeral=True)
            return

        target = user or interaction.user
        result = {'was_subbed': False}

        def _unsub(data):
            if not isinstance(data, dict) or 'subscribers' not in data:
                return data
            subs = data['subscribers'].get('schachrallye', [])
            if target.id in subs:
                subs.remove(target.id)
                result['was_subbed'] = True
            return data

        atomic_update(TURNIER_FILE, _unsub)
        if result['was_subbed']:
            if user:
                await interaction.response.send_message(
                    f'\u2705 **{target.display_name}** unsubscribed.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    '\u2705 Schachrallye-Erinnerungen abbestellt.',
                    ephemeral=True)
        else:
            name = f'**{target.display_name}**' if user else 'Du'
            verb = 'war' if user else 'warst'
            await interaction.response.send_message(
                f'{name} {verb} nicht subscribed.', ephemeral=True)

    # --- /turnier_sub + /turnier_unsub -----------------------------------

    @tree.command(name='turnier_sub',
                  description='Fuer einen Turnier-Tag subscriben (Ping bei neuen Turnieren)')
    @discord.app_commands.describe(
        tag='Tag fuer den du gepingt werden willst (z.B. schnellschach, blitz, 960, klassisch, jugend, senioren)',
        user='Anderen User subscriben (nur Admin)')
    async def cmd_turnier_sub(interaction: discord.Interaction,
                              tag: str = '', user: discord.User = None):
        tag = tag.strip().lower()

        # Ohne Tag: eigene Subs anzeigen
        if not tag:
            data = atomic_read(TURNIER_FILE, default=dict)
            if not data:
                data = _fresh_default()
            subs = data.get('subscribers', {})
            uid = interaction.user.id
            my_tags = sorted(t for t, uids in subs.items() if uid in uids)
            if my_tags:
                tag_list = ', '.join(f'`{t}`' for t in my_tags)
                await interaction.response.send_message(
                    f'Deine Turnier-Abos: {tag_list}', ephemeral=True)
            else:
                await interaction.response.send_message(
                    'Du hast noch keine Turnier-Tags abonniert.\n'
                    'Nutze `/turnier_sub tag:schnellschach` um einen Tag zu abonnieren.',
                    ephemeral=True)
            return

        if user and not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins koennen andere User subscriben.',
                ephemeral=True)
            return

        target = user or interaction.user
        result = {'already': False}

        def _sub(data):
            if not isinstance(data, dict) or 'subscribers' not in data:
                data = _fresh_default()
            subs = data['subscribers'].setdefault(tag, [])
            if target.id in subs:
                result['already'] = True
                return data
            subs.append(target.id)
            return data

        atomic_update(TURNIER_FILE, _sub)
        if result['already']:
            name = f'**{target.display_name}**' if user else 'Du bist'
            suffix = f'ist bereits fuer `{tag}` subscribed.' if user else f'bereits fuer `{tag}` subscribed.'
            await interaction.response.send_message(
                f'{name} {suffix}', ephemeral=True)
        else:
            if user:
                await interaction.response.send_message(
                    f'\u2705 **{target.display_name}** fuer Tag `{tag}` subscribed.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'\u2705 Du wirst bei neuen Turnieren mit Tag `{tag}` gepingt.',
                    ephemeral=True)
            # DM an den subscribten User
            try:
                dm = await target.create_dm()
                await dm.send(
                    f'Du wurdest fuer den Turnier-Tag **{tag}** angemeldet! '
                    f'Bei neuen Turnieren mit diesem Tag wirst du im Channel gepingt.\n'
                    f'Mit `/turnier_unsub tag:{tag}` kannst du dich jederzeit abmelden.'
                )
            except discord.Forbidden:
                log.warning('Turnier-Sub-DM an %s nicht moeglich (DMs deaktiviert).', target.id)
            except Exception:
                log.warning('Turnier-Sub-DM an %s fehlgeschlagen.', target.id)

    @tree.command(name='turnier_unsub',
                  description='Turnier-Tag-Abo abbestellen')
    @discord.app_commands.describe(
        tag='Tag den du abbestellen willst (z.B. schnellschach, blitz, 960, schachrallye)',
        user='Anderen User unsubscriben (nur Admin)')
    async def cmd_turnier_unsub(interaction: discord.Interaction,
                                tag: str, user: discord.User = None):
        if user and not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur Admins koennen andere User unsubscriben.',
                ephemeral=True)
            return

        tag = tag.strip().lower()
        target = user or interaction.user
        result = {'was_subbed': False}

        def _unsub(data):
            if not isinstance(data, dict) or 'subscribers' not in data:
                return data
            subs = data['subscribers'].get(tag, [])
            if target.id in subs:
                subs.remove(target.id)
                result['was_subbed'] = True
            return data

        atomic_update(TURNIER_FILE, _unsub)
        if result['was_subbed']:
            if user:
                await interaction.response.send_message(
                    f'\u2705 **{target.display_name}** von Tag `{tag}` unsubscribed.',
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f'\u2705 Tag `{tag}` abbestellt.',
                    ephemeral=True)
        else:
            name = f'**{target.display_name}**' if user else 'Du'
            verb = 'war' if user else 'warst'
            await interaction.response.send_message(
                f'{name} {verb} nicht fuer `{tag}` subscribed.', ephemeral=True)

    # --- Parse-Logik (shared zwischen Command und Auto-Loop) ---------------

    def _build_pending_embed(event: dict) -> discord.Embed:
        """Baut ein Embed fuer ein pending Event (Review-DMs + /turnier_pending)."""
        dt = event.get('datum_text', event.get('datum', ''))
        ort = _shorten_ort(event.get('ort', ''))
        tags = event.get('tags', [])
        desc = f"\U0001f4c5 `{dt}`"
        if ort:
            desc += f" \u00b7 {ort}"
        if tags:
            desc += '\n' + ' '.join(f'`{t}`' for t in tags)

        embed = discord.Embed(
            title=event.get('name', 'Neues Turnier'),
            description=desc,
            color=0xf39c12,  # Orange fuer Pending
        )
        embed.set_footer(text=f'Event #{event["id"]}')
        return embed

    async def _notify_reviewers(added_events: list[dict]):
        """Sendet Review-DMs an alle Reviewer fuer neue Events."""
        from commands.turnier_buttons import TurnierReviewView

        data = atomic_read(TURNIER_FILE, default=dict)
        reviewers = data.get('reviewers', [])
        if not reviewers:
            return

        # Event-IDs aus der JSON holen (added_events enthaelt die Roh-Daten,
        # wir brauchen die gespeicherten mit ID)
        all_events = data.get('events', [])
        # Neue Events matchen ueber (datum, name)
        added_keys = {(a['datum'], a['name']) for a in added_events}
        pending = [e for e in all_events
                   if (e['datum'], e.get('name', '')) in added_keys
                   and e.get('approved') is False]

        for event in pending:
            embed = _build_pending_embed(event)

            for uid in reviewers:
                try:
                    user = _bot.get_user(uid) or await _bot.fetch_user(uid)
                    dm = await user.create_dm()
                    view = TurnierReviewView()
                    await dm.send(embed=embed, view=view)
                except Exception:
                    log.warning('Review-DM an %s fehlgeschlagen (Event #%d)',
                                uid, event['id'])

    async def _parse_and_post() -> list[dict]:
        """Fetcht Termine, merged in JSON, ggf. Review oder direkt posten.

        Returns: Liste der neu hinzugefuegten Events.
        """
        new_events = await asyncio.to_thread(_fetch_termine)

        added: list[dict] = []
        merge_result = {}

        def _merge(data):
            if not isinstance(data, dict) or 'events' not in data:
                data = _fresh_default()
            merge_result['reviewers'] = data.get('reviewers', [])
            existing = {(e['datum'], e.get('name', '')) for e in data['events']}
            for t in new_events:
                if (t['datum'], t['name']) in existing:
                    continue
                new_id = data.get('next_id', 1)
                entry = {
                    'id': new_id,
                    'datum': t['datum'],
                    'datum_text': t.get('datum_text', ''),
                    'name': t['name'],
                    'ort': t['ort'],
                    'link': t.get('link', ''),
                    'tags': t.get('tags', []),
                    'approved': False,
                }
                if 'schachrallye' in t.get('tags', []):
                    entry['reminded'] = False
                data['events'].append(entry)
                data['next_id'] = new_id + 1
                added.append(t)
            return data

        atomic_update(TURNIER_FILE, _merge)
        reviewers = merge_result.get('reviewers', [])

        if added:
            if reviewers:
                await _notify_reviewers(added)
            else:
                log.warning('Neue Turniere warten auf Freigabe, aber keine Reviewer konfiguriert. '
                            'Nutze /turnier_review zum Subscriben.')

        return added

    # --- /turnier_parse -------------------------------------------------

    @tree.command(name='turnier_parse',
                  description='Termine von tirol.chess.at importieren (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_turnier_parse(interaction: discord.Interaction):
        if not is_privileged(interaction):
            await interaction.response.send_message('⚠️ Nur für Admins.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            added = await _parse_and_post()
        except Exception as e:
            log.exception('turnier_parse fehlgeschlagen')
            await interaction.followup.send(
                f'\u274c Fehler beim Laden von {RALLYE_URL}: {e}', ephemeral=True)
            return

        if added:
            rallye_added = [a for a in added if 'schachrallye' in a.get('tags', [])]
            turnier_added = [a for a in added if 'schachrallye' not in a.get('tags', [])]
            parts = []
            if rallye_added:
                lines = [_format_turnier_line(a) for a in rallye_added]
                parts.append(f"**Rallye** \u2014 {len(rallye_added)} neu (pending):\n" + '\n'.join(lines))
            if turnier_added:
                lines = [_format_turnier_line(a) for a in turnier_added]
                parts.append(f"**Turniere** \u2014 {len(turnier_added)} neu (pending):\n" + '\n'.join(lines))
            desc = '\n\n'.join(parts)
            if len(desc) > 4096:
                desc = desc[:4093] + '...'
            embed = discord.Embed(
                title='\u2705 Import abgeschlossen',
                description=desc,
                color=EMBED_COLOR,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                'Alle Termine bereits vorhanden \u2014 keine neuen hinzugefuegt.',
                ephemeral=True)

    # --- /turnier ------------------------------------------------------------

    @tree.command(name='turnier',
                  description='Alle zukuenftigen Turniere anzeigen (von tirol.chess.at)')
    async def cmd_turnier(interaction: discord.Interaction):
        data = atomic_read(TURNIER_FILE, default=dict)
        if not data:
            data = _fresh_default()
        events = data.get('events', [])

        today = date.today()
        future = [e for e in events
                  if (_parse_stored(e['datum']) or date.min) >= today
                  and e.get('approved', True) is not False]
        future.sort(key=lambda e: e['datum'])

        if not future:
            await interaction.response.send_message(
                'Keine anstehenden Turniere vorhanden. '
                'Ein Admin kann mit `/turnier_parse` Termine importieren.',
                ephemeral=True)
            return

        lines = [_format_turnier_line(e) for e in future]
        desc = '\n'.join(lines)
        if len(desc) > 4096:
            desc = desc[:4093] + '...'

        embed = discord.Embed(
            title='\U0001f3c6 Turniere \u2014 Tirol',
            description=desc,
            color=EMBED_COLOR,
        )
        embed.set_footer(text='Quelle: tirol.chess.at/termine/')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- /turnier_review (Reviewer sub/unsub) ---------------------------------

    @tree.command(name='turnier_review',
                  description='Als Turnier-Reviewer subscriben/unsubscriben (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_turnier_review(interaction: discord.Interaction):
        if not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur fuer Admins/Moderatoren.', ephemeral=True)
            return

        uid = interaction.user.id
        result = {'action': ''}

        def _toggle(data):
            if not isinstance(data, dict) or 'events' not in data:
                data = _fresh_default()
            reviewers = data.setdefault('reviewers', [])
            if uid in reviewers:
                reviewers.remove(uid)
                result['action'] = 'unsub'
            else:
                reviewers.append(uid)
                result['action'] = 'sub'
            return data

        atomic_update(TURNIER_FILE, _toggle)

        if result['action'] == 'sub':
            await interaction.response.send_message(
                '\u2705 Du bist jetzt Turnier-Reviewer. '
                'Neue Turniere muessen von dir freigegeben werden, '
                'bevor sie im Channel gepostet werden.',
                ephemeral=True)
        else:
            await interaction.response.send_message(
                '\u2705 Turnier-Review abbestellt.',
                ephemeral=True)

    # --- /turnier_pending (pending Events anzeigen) -------------------------

    @tree.command(name='turnier_pending',
                  description='Ausstehende Turniere anzeigen (Admin)')
    @discord.app_commands.default_permissions(administrator=True)
    async def cmd_turnier_pending(interaction: discord.Interaction):
        if not is_privileged(interaction):
            await interaction.response.send_message(
                '\u26a0\ufe0f Nur fuer Admins/Moderatoren.', ephemeral=True)
            return

        data = atomic_read(TURNIER_FILE, default=dict)
        if not data:
            data = _fresh_default()
        events = data.get('events', [])
        pending = [e for e in events if e.get('approved') is False]

        if not pending:
            await interaction.response.send_message(
                'Keine ausstehenden Turniere.', ephemeral=True)
            return

        from commands.turnier_buttons import TurnierReviewView

        pending.sort(key=lambda e: e.get('datum', ''))
        await interaction.response.defer(ephemeral=True)
        for event in pending:
            embed = _build_pending_embed(event)
            view = TurnierReviewView()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # --- Reminder-Loop -------------------------------------------------------

    @tasks.loop(hours=6)
    async def _rallye_reminder():
        try:
            await _rallye_reminder_inner()
        except Exception:
            log.exception('Rallye-Reminder-Loop fehlgeschlagen')

    async def _rallye_reminder_inner():
        if not _tournament_channel_id:
            return
        channel = _bot.get_channel(_tournament_channel_id)
        if not channel:
            return

        data = atomic_read(TURNIER_FILE, default=dict)
        if not data or not isinstance(data, dict):
            return
        events = data.get('events', [])
        subs = data.get('subscribers', {}).get('schachrallye', [])
        if not events or not subs:
            return

        today = date.today()
        remind_ids = []

        for event in events:
            if 'schachrallye' not in event.get('tags', []):
                continue
            if event.get('approved', True) is False:
                continue
            if event.get('reminded'):
                continue
            d = _parse_stored(event['datum'])
            if d is None:
                continue
            if d <= today:
                continue
            if (d - today).days <= 7:
                remind_ids.append(event['id'])
                mentions = ' '.join(f'<@{uid}>' for uid in subs)
                ts = int(datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc).timestamp())
                name = event.get('name', '')
                ort = _shorten_ort(event.get('ort', ''))
                desc_text = f'**Termin #{event["id"]}**'
                if name:
                    desc_text += f' \u2014 **{name}**'
                desc_text += f' am <t:{ts}:D>'
                if ort:
                    desc_text += f' \u00b7 {ort}'
                embed = discord.Embed(
                    title='\U0001f3c7 Schachrallye \u2014 Erinnerung',
                    description=desc_text,
                    color=EMBED_COLOR,
                )
                try:
                    await channel.send(content=mentions, embed=embed)
                except Exception:
                    log.exception('Rallye-Erinnerung fehlgeschlagen fuer Event #%d', event['id'])

        if remind_ids:
            def _mark_reminded(data):
                if not isinstance(data, dict):
                    return data
                for event in data.get('events', []):
                    if event['id'] in remind_ids:
                        event['reminded'] = True
                return data
            atomic_update(TURNIER_FILE, _mark_reminded)

    # --- Auto-Parse-Loop (taeglich 18:00 UTC) --------------------------------

    @tasks.loop(time=time(hour=18, minute=0))
    async def _auto_parse():
        try:
            added = await _parse_and_post()
            if added:
                log.info('Auto-Parse: %d neue Turniere importiert.', len(added))
            await asyncio.to_thread(_prune_old_events)
        except Exception:
            log.exception('Auto-Parse fehlgeschlagen')

    @bot.listen('on_ready')
    async def _start_loops():
        if not _rallye_reminder.is_running():
            _rallye_reminder.start()
        if not _auto_parse.is_running():
            _auto_parse.start()

    if hasattr(bot, '_task_loops'):
        bot._task_loops['rallye_reminder'] = _rallye_reminder
        bot._task_loops['auto_parse'] = _auto_parse
