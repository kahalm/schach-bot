"""
Unit-Tests fuer core/json_store.py.

Standalone-Script. Kein Discord-Mocking noetig (pure stdlib).

Ausfuehren: python tests/test_json_store.py
"""

import sys
import os
import json
import tempfile
import shutil
import threading

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from core.json_store import _lock_for, _locks, atomic_read, atomic_write, atomic_update

# ---------------------------------------------------------------------------
# Test-Runner
# ---------------------------------------------------------------------------

PASS = 'OK  '
FAIL = 'FAIL'
total = 0
failed = 0


def check(label, ok, detail=''):
    global total, failed
    total += 1
    if ok:
        print(f'  {PASS} {label}')
    else:
        failed += 1
        msg = f'  {FAIL} {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir = None


def setup():
    global _tmpdir
    _tmpdir = tempfile.mkdtemp(prefix='schach_test_json_store_')
    _locks.clear()


def teardown():
    global _tmpdir
    if _tmpdir:
        shutil.rmtree(_tmpdir, ignore_errors=True)
        _tmpdir = None
    _locks.clear()


def tmp(name):
    return os.path.join(_tmpdir, name)


# ===================================================================
# TESTS
# ===================================================================


def test_lock_for():
    """Tests fuer _lock_for."""
    print('[_lock_for]')
    setup()
    try:
        p = tmp('a.json')

        # Gleicher Pfad = gleicher Lock
        lock1 = _lock_for(p)
        lock2 = _lock_for(p)
        check('gleicher Pfad = gleicher Lock', lock1 is lock2)

        # Verschiedene Pfade = verschiedene Locks
        lock3 = _lock_for(tmp('b.json'))
        check('verschiedene Pfade = verschiedene Locks', lock1 is not lock3)

        # Lock ist ein threading.Lock
        check('Lock-Typ', isinstance(lock1, type(threading.Lock())))

        # Relativ vs absolut: _lock_for normalisiert auf abspath
        rel_path = os.path.relpath(p)
        lock4 = _lock_for(rel_path)
        check('relativ vs absolut: gleicher Lock', lock4 is lock1)
    finally:
        teardown()


def test_atomic_read():
    """Tests fuer atomic_read."""
    print('[atomic_read]')
    setup()
    try:
        # Nicht-existente Datei: Default {}
        result = atomic_read(tmp('missing.json'))
        check('nicht-existent: leeres Dict', result == {})

        # Nicht-existente Datei: callable Default
        result = atomic_read(tmp('missing2.json'), default=list)
        check('nicht-existent: callable Default (list)', result == [])

        # Nicht-existente Datei: statischer Default
        result = atomic_read(tmp('missing3.json'), default={'key': 'val'})
        check('nicht-existent: statischer Default', result == {'key': 'val'})

        # Valide JSON lesen
        p = tmp('valid.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'foo': 42}, f)
        result = atomic_read(p)
        check('valide JSON lesen', result == {'foo': 42})

        # Korrupte JSON: Default
        p2 = tmp('corrupt.json')
        with open(p2, 'w', encoding='utf-8') as f:
            f.write('{broken')
        result = atomic_read(p2)
        check('korrupte JSON: Default {}', result == {})

        # Leere Datei: Default
        p3 = tmp('empty.json')
        with open(p3, 'w', encoding='utf-8') as f:
            pass
        result = atomic_read(p3)
        check('leere Datei: Default {}', result == {})
    finally:
        teardown()


def test_atomic_write():
    """Tests fuer atomic_write."""
    print('[atomic_write]')
    setup()
    try:
        # Schreiben + Rücklesen
        p = tmp('write1.json')
        atomic_write(p, {'x': 1})
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        check('Schreiben + Rücklesen', data == {'x': 1})

        # Directory wird erstellt
        p2 = os.path.join(_tmpdir, 'sub', 'dir', 'write2.json')
        atomic_write(p2, [1, 2, 3])
        with open(p2, encoding='utf-8') as f:
            data = json.load(f)
        check('Directory erstellt', data == [1, 2, 3])

        # Überschreiben
        atomic_write(p, {'x': 99})
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        check('Überschreiben', data == {'x': 99})

        # atomic_read nach write
        result = atomic_read(p)
        check('atomic_read nach write', result == {'x': 99})
    finally:
        teardown()


def test_atomic_update():
    """Tests fuer atomic_update."""
    print('[atomic_update]')
    setup()
    try:
        # Update nicht-existente Datei
        p = tmp('update1.json')
        result = atomic_update(p, lambda d: {**d, 'a': 1})
        check('Update nicht-existente Datei', result == {'a': 1})
        check('Datei existiert danach', os.path.exists(p))

        # Update existente Datei
        result = atomic_update(p, lambda d: {**d, 'b': 2})
        check('Update existente Datei', result == {'a': 1, 'b': 2})

        # Callable Default
        p2 = tmp('update2.json')
        result = atomic_update(p2, lambda d: d + [42], default=list)
        check('callable Default (list)', result == [42])

        # Sequentielle Updates
        p3 = tmp('update3.json')
        for i in range(5):
            atomic_update(p3, lambda d, i=i: {**d, str(i): i})
        result = atomic_read(p3)
        check('sequentielle Updates', len(result) == 5 and result['4'] == 4)
    finally:
        teardown()


def test_concurrent_writes():
    """Tests fuer Thread-Safety mit parallelen Writes."""
    print('[concurrent writes]')
    setup()
    try:
        p = tmp('concurrent.json')
        atomic_write(p, {'counter': 0})

        errors = []

        def increment():
            try:
                atomic_update(p, lambda d: {'counter': d['counter'] + 1})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = atomic_read(p)
        check('kein Datenverlust (counter=10)', result['counter'] == 10,
              f'counter={result.get("counter")}')
        check('keine Fehler', len(errors) == 0, str(errors))

        # Valide JSON nach Konkurrenz
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        check('valide JSON nach Konkurrenz', data['counter'] == 10)
    finally:
        teardown()


# ===================================================================
# MAIN
# ===================================================================

if __name__ == '__main__':
    print('=== test_json_store.py ===\n')
    test_lock_for()
    test_atomic_read()
    test_atomic_write()
    test_atomic_update()
    test_concurrent_writes()
    print(f'\n--- {total} checks, {failed} failed ---')
    sys.exit(1 if failed else 0)
