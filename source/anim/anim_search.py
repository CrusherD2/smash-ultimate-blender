"""Match animation list rows by filename or by the move they represent.

Typing the file stem still works. Common names do too: "jab" finds attack11,
attack12, attack13, and the rapid jab, and "side special" finds specials.
"""
import fnmatch
import re
from functools import lru_cache


def _phrase(text):
    text = text.casefold().replace('_', ' ').replace('-', ' ')
    text = re.sub(r'[^a-z0-9\s]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _rule(pattern, phrases):
    return re.compile(pattern), tuple(_phrase(phrase) for phrase in phrases)


# Patterns run against the filename with underscores and hyphens removed.
# A row keeps every alias from every pattern it matches.
_RULES = (
    _rule(r'attack11(?!\d)', ('jab', 'jabs', 'jab 1', 'neutral attack')),
    _rule(r'attack12(?!\d)', ('jab', 'jabs', 'jab 2', 'neutral attack')),
    _rule(r'attack13(?!\d)', ('jab', 'jabs', 'jab 3', 'neutral attack')),
    _rule(r'attack1(?!\d)', ('jab', 'jabs', 'jab 1', 'neutral attack')),
    _rule(r'attack01(?!\d)', ('jab', 'jabs', 'jab 1', 'neutral attack')),
    _rule(r'attack100start', ('jab', 'jabs', 'rapid jab', 'rapid jab start')),
    _rule(r'attack100end', ('jab', 'jabs', 'rapid jab', 'rapid jab finisher', 'jab finisher')),
    _rule(r'attack100(?!start|end)', ('jab', 'jabs', 'rapid jab', 'infinite jab')),
    _rule(r'attackdash', ('dash attack',)),
    _rule(r'attacks3hi', ('forward tilt', 'side tilt', 'ftilt', 'f tilt', 'angled up', 'tilt up')),
    _rule(r'attacks3lw', ('forward tilt', 'side tilt', 'ftilt', 'f tilt', 'angled down', 'tilt down')),
    _rule(r'attacks3(?!hi|lw)', ('forward tilt', 'side tilt', 'ftilt', 'f tilt')),
    _rule(r'attackhi3(?!\d)', ('up tilt', 'utilt', 'u tilt')),
    _rule(r'attacklw3(?!\d)', ('down tilt', 'dtilt', 'd tilt')),
    _rule(r'attacks4hi', ('forward smash', 'side smash', 'fsmash', 'f smash', 'angled up', 'smash up')),
    _rule(r'attacks4lw', ('forward smash', 'side smash', 'fsmash', 'f smash', 'angled down', 'smash down')),
    _rule(r'attacks4(?!hi|lw)', ('forward smash', 'side smash', 'fsmash', 'f smash')),
    _rule(r'attackhi4(?!\d)', ('up smash', 'usmash', 'u smash')),
    _rule(r'attacklw4(?!\d)', ('down smash', 'dsmash', 'd smash')),
    _rule(r'attackairn', ('neutral air', 'nair', 'n air')),
    _rule(r'attackairf', ('forward air', 'fair', 'f air')),
    _rule(r'attackairb', ('back air', 'bair', 'b air')),
    _rule(r'attackairhi', ('up air', 'uair', 'u air')),
    _rule(r'attackairlw', ('down air', 'dair', 'd air')),
    _rule(r'landingair', ('landing', 'aerial landing')),
    _rule(r'landingheavy', ('landing', 'hard landing', 'heavy landing')),
    _rule(r'landinglight', ('landing', 'soft landing', 'light landing')),
    _rule(r'(?<![a-z])landing(?!air|heavy|light)', ('landing',)),
    _rule(r'aircatch', ('zair', 'aerial grab', 'air grab', 'grab')),
    _rule(r'catchdash', ('dash grab', 'grab')),
    _rule(r'catchturn', ('pivot grab', 'grab')),
    _rule(r'catchattack', ('pummel', 'grab pummel', 'grab')),
    _rule(r'catchcut', ('grab whiff', 'whiff grab', 'grab miss', 'grab')),
    _rule(r'(?<![a-z])catch(?!dash|turn|attack|cut)', ('grab', 'standing grab', 'grab hold')),
    _rule(r'(?<![a-z])throwf', ('forward throw', 'fthrow', 'f throw')),
    _rule(r'(?<![a-z])throwb', ('back throw', 'bthrow', 'b throw')),
    _rule(r'(?<![a-z])throwhi', ('up throw', 'uthrow', 'u throw')),
    _rule(r'(?<![a-z])throwlw', ('down throw', 'dthrow', 'd throw')),
    _rule(r'capture(?:pulled|wait|damage|cut|jump)', ('grabbed', 'captured')),
    _rule(r'specialairs', ('side special', 'forward special', 'side b', 'forward b', 'b move', 'aerial side special')),
    _rule(r'specialairn', ('neutral special', 'neutral b', 'b move', 'aerial neutral special')),
    _rule(r'specialairhi', ('up special', 'up b', 'recovery', 'b move', 'aerial up special')),
    _rule(r'specialairlw', ('down special', 'down b', 'b move', 'aerial down special')),
    _rule(r'specials', ('side special', 'forward special', 'side b', 'forward b', 'b move')),
    _rule(r'specialn', ('neutral special', 'neutral b', 'b move')),
    _rule(r'specialhi', ('up special', 'up b', 'recovery', 'b move')),
    _rule(r'speciallw', ('down special', 'down b', 'b move')),
    _rule(r'(?<![a-z])final', ('final smash',)),
    _rule(r'guardon', ('shield', 'shield start', 'shield on')),
    _rule(r'guardoff', ('shield', 'shield drop', 'shield off', 'unshield')),
    _rule(r'guarddamage', ('shield', 'shield stun', 'shield hit', 'shield damage')),
    _rule(r'justshield', ('parry', 'perfect shield', 'powershield', 'just shield', 'shield')),
    _rule(r'(?<![a-z])guard(?!on|off|damage)', ('shield', 'shielding')),
    _rule(r'escapeair', ('air dodge', 'airdodge', 'directional air dodge')),
    _rule(r'escapef', ('forward roll', 'roll forward', 'roll')),
    _rule(r'escapeb', ('back roll', 'roll back', 'roll')),
    _rule(r'escapen', ('spot dodge', 'spotdodge')),
    _rule(r'(?<![a-z])escape(?!air|[fbn])', ('spot dodge', 'spotdodge')),
    _rule(r'damagefly|damagefall', ('hitstun', 'tumble', 'knockback', 'launch', 'damage')),
    _rule(r'(?<![a-z])damage(?!fly|fall)', ('flinch', 'hitstun', 'damage')),
    _rule(r'downattack', ('getup attack', 'getup', 'wakeup attack')),
    _rule(r'downforward', ('getup roll forward', 'getup roll', 'getup')),
    _rule(r'downback', ('getup roll back', 'getup roll', 'getup')),
    _rule(r'downstand', ('getup', 'neutral getup')),
    _rule(r'downwait|downbound|downdamage', ('knockdown', 'downed', 'lie down')),
    _rule(r'(?<![a-z])down(?!attack|forward|back|stand|wait|bound|damage)', ('knockdown', 'downed')),
    _rule(r'passivestandf', ('tech', 'tech roll', 'tech roll forward')),
    _rule(r'passivestandb', ('tech', 'tech roll', 'tech roll back')),
    _rule(r'passivewalljump', ('wall tech', 'wall tech jump', 'tech')),
    _rule(r'passivewall', ('wall tech', 'tech')),
    _rule(r'(?<![a-z])passive(?!stand|wall)', ('tech', 'tech in place', 'neutral tech')),
    _rule(r'slipattack', ('trip attack', 'trip', 'slip')),
    _rule(r'slipstand', ('trip getup', 'trip', 'slip')),
    _rule(r'(?<![a-z])slip(?!attack|stand)', ('trip', 'slip', 'stumble')),
    _rule(r'furafura|furasleep', ('stun', 'dizzy', 'shield break')),
    _rule(r'(?<![a-z])bury', ('bury', 'buried')),
    _rule(r'cliffcatch', ('ledge catch', 'ledge snap')),
    _rule(r'cliffwait', ('ledge hang', 'ledge wait', 'hanging')),
    _rule(r'cliffattack', ('ledge attack',)),
    _rule(r'cliffclimb', ('ledge getup', 'ledge climb', 'ledge regular')),
    _rule(r'cliffescape', ('ledge roll',)),
    _rule(r'cliffjump', ('ledge jump',)),
    _rule(r'cliffrobbed', ('ledge trump', 'ledge steal')),
    _rule(r'(?<![a-z])cliff', ('ledge',)),
    _rule(r'a\d{2}wait', ('idle', 'wait', 'standing')),
    _rule(r'walk', ('walk', 'walking')),
    _rule(r'runbrake', ('run stop', 'run brake', 'skid')),
    _rule(r'(?<![a-z])run(?!brake)', ('run', 'running')),
    _rule(r'(?<!attack)(?<!catch)(?<![a-z])dash', ('dash', 'initial dash')),
    _rule(r'turnrun', ('run turn', 'turn run')),
    _rule(r'(?<![a-z])turn(?!run)', ('turn', 'turnaround')),
    _rule(r'jumpaerial', ('double jump', 'air jump', 'midair jump')),
    _rule(r'(?<![a-z])jump(?!aerial)', ('jump', 'jumpsquat', 'jump squat')),
    _rule(r'fallspecial', ('special fall',)),
    _rule(r'fallaerial|(?<![a-z])fall(?!special)', ('fall', 'falling')),
    _rule(r'squatwait', ('crouch', 'crouching')),
    _rule(r'squatrv', ('uncrouch', 'crouch release')),
    _rule(r'squat[fb]', ('crawl',)),
    _rule(r'(?<![a-z])squat(?!wait|rv|[fb])', ('crouch',)),
    _rule(r'ottotto', ('teeter', 'edge', 'edge teeter', 'edge balance')),
    _rule(r'(?<![a-z])pass(?!ive)', ('platform drop', 'drop through')),
    _rule(r'appealhi', ('up taunt', 'taunt up', 'taunt')),
    _rule(r'appeallw', ('down taunt', 'taunt down', 'taunt')),
    _rule(r'appeals[lr]', ('side taunt', 'taunt side', 'taunt')),
    _rule(r'(?<![a-z])appeal', ('taunt',)),
    _rule(r'(?<![a-z])win(?![a-z])', ('victory', 'win')),
    _rule(r'(?<![a-z])lose', ('lose', 'loss', 'defeat')),
    _rule(r'(?<![a-z])entry', ('entrance', 'intro', 'spawn')),
    _rule(r'rebirth', ('respawn', 'rebirth')),
    _rule(r'(?<![a-z])item', ('item',)),
    _rule(r'(?<![a-z])swim', ('swim',)),
    _rule(r'ladder', ('ladder',)),
    _rule(r'walljump', ('wall jump',)),
    _rule(r'walldamage', ('wall hit', 'wall damage')),
    _rule(r'stepjump', ('footstool',)),
)


def _compact(name):
    key = name.casefold().strip()
    if key.endswith('.nuanmb'):
        key = key[:-7]
    return key.replace('_', '').replace('-', '')


@lru_cache(maxsize=4096)
def aliases_for(name):
    key = _compact(name)
    found = []
    for pattern, phrases in _RULES:
        if pattern.search(key):
            found.extend(phrases)
    return tuple(dict.fromkeys(found))


def _name_match(name, query):
    return fnmatch.fnmatchcase(name.casefold(), '*' + query.casefold() + '*')


def _word_match(alias_word, query_word, allow_prefix):
    if alias_word == query_word:
        return True
    return bool(allow_prefix and alias_word.startswith(query_word))


def _phrase_match(alias, query):
    alias_words = alias.split()
    query_words = query.split()
    if query_words and len(query_words) <= len(alias_words):
        allow_prefix = len(query_words) > 1
        span = len(query_words)
        for start in range(len(alias_words) - span + 1):
            if all(_word_match(alias_words[start + index], query_words[index], allow_prefix or len(query_words[index]) >= 3)
                   for index in range(span)):
                return True
    if ' ' not in query and len(query) >= 4:
        compact = alias.replace(' ', '')
        if compact == query or compact.startswith(query):
            return True
    return False


def animation_matches(name, query):
    """True when the filename contains the query, or the query names that move."""
    query = (query or '').strip()
    if not query:
        return True
    if _name_match(name, query):
        return True
    phrase = _phrase(query)
    if len(phrase) < 2:
        return False
    return any(_phrase_match(alias, phrase) for alias in aliases_for(name))


_FILTER_CACHE = {}


def _same_names(cached, items):
    if len(cached) != len(items):
        return False
    for previous, item in zip(cached, items):
        if previous != item.name:
            return False
    return True


def list_filter(ui_list, items):
    """Flags, display order, and visible source indices for an animation UIList.

    Display order follows the list's name sort and reverse toggles. Visible
    indices follow that order so shift-click range select matches the rows
    on screen.
    """
    filter_name = getattr(ui_list, 'filter_name', '') or ''
    invert = bool(getattr(ui_list, 'use_filter_invert', False))
    alpha = bool(getattr(ui_list, 'use_filter_sort_alpha', False))
    reverse = bool(getattr(ui_list, 'use_filter_sort_reverse', False))
    key = (filter_name, invert, alpha, reverse)
    slot = _FILTER_CACHE.get(id(ui_list))
    if slot is not None and slot[0] == key and _same_names(slot[1], items):
        return slot[2]

    bit = ui_list.bitflag_filter_item
    query = filter_name.strip()
    if query:
        flags = [bit if animation_matches(item.name, query) else 0 for item in items]
    else:
        flags = [bit] * len(items)
    if invert:
        flags = [0 if flag else bit for flag in flags]

    order = list(range(len(items)))
    reordered = False
    if alpha:
        order.sort(key=lambda index: items[index].name.casefold())
        reordered = True
    if reverse:
        order.reverse()
        reordered = True
    visible = [index for index in order if flags[index] & bit]
    result = (flags, order if reordered else [], visible)
    _FILTER_CACHE[id(ui_list)] = (key, tuple(item.name for item in items), result)
    if len(_FILTER_CACHE) > 4:
        current = _FILTER_CACHE[id(ui_list)]
        _FILTER_CACHE.clear()
        _FILTER_CACHE[id(ui_list)] = current
    return result
