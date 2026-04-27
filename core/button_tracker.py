"""Wiederverwendbares Click-Tracking fuer Button-Views mit Mutex-Paaren."""

from collections import OrderedDict


class ClickTracker:
    """In-Memory Click-Tracking mit Toggle, Mutex-Paaren und LRU-Eviction."""

    def __init__(self, mutex_pairs: dict[str, str], cap: int = 500):
        self._mutex_pairs = mutex_pairs
        self._cap = cap
        # msg_id -> emoji -> set[user_id]
        self._clicks: OrderedDict[int, dict[str, set[int]]] = OrderedDict()

    def count(self, msg_id: int, emoji: str) -> int:
        return len(self._clicks.get(msg_id, {}).get(emoji, set()))

    def apply_click(self, msg_id: int, emoji: str, user_id: int
                    ) -> tuple[int, str | None]:
        """Toggle-Klick. Gibt (delta, removed_partner) zurueck."""
        while len(self._clicks) >= self._cap and msg_id not in self._clicks:
            self._clicks.popitem(last=False)
        by_emoji = self._clicks.setdefault(msg_id, {})

        removed: str | None = None
        partner = self._mutex_pairs.get(emoji)
        if partner:
            partner_users = by_emoji.get(partner)
            if partner_users and user_id in partner_users:
                partner_users.remove(user_id)
                removed = partner

        users = by_emoji.setdefault(emoji, set())
        if user_id in users:
            users.remove(user_id)
            return -1, removed
        users.add(user_id)
        return +1, removed

    def get_emoji_users(self, msg_id: int) -> dict[str, set[int]]:
        """Gibt das emoji->users Dict fuer eine msg_id zurueck (oder leer)."""
        return self._clicks.get(msg_id, {})

    def clear(self):
        self._clicks.clear()
