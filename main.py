import asyncio
import time
import requests
import urllib3
import traceback
import json
import re
import random
import os
from lcu_driver import Connector

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

connector = Connector()
global am_i_assigned, am_i_picking, am_i_banning, ban_number, phase, picks, bans, in_game, have_i_prepicked
am_i_assigned = False
am_i_banning = False
am_i_picking = False
in_game = False
phase = ''
have_i_prepicked = False

# Champion ids the logged-in account actually owns (None until first successful fetch).
# LCU accepts a PATCH pick for an unowned champion ID with no error at the HTTP layer in
# some client versions, so ownership must be checked ourselves before ever attempting a pick.
owned_champion_ids = None

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def migrate_config(cfg):
    """Convert old champions.{role}.order format to layouts + roles format"""
    if "layouts" in cfg:
        return cfg
    layouts = {}
    roles = {}
    nid = 1
    for role, data in cfg.get("champions", {}).items():
        ids = []
        for e in data.get("order", []):
            if isinstance(e, str):
                e = {"champion": e, "spells": [], "runes": []}
            c = e.get("champion", "")
            s = e.get("spells", [])
            r = e.get("runes", [])
            found = next((lid for lid, l in layouts.items()
                          if l["champion"] == c and l["spells"] == s and l["runes"] == r), None)
            if found:
                ids.append(found)
            else:
                lid = str(nid); nid += 1
                layouts[lid] = {"champion": c, "spells": s, "runes": r}
                ids.append(lid)
        roles[role] = ids
    fb = cfg.get("fallback", {})
    new_fb = {"mode": fb.get("mode", "random_default"), "layout_id": ""}
    if fb.get("mode") == "fallback_layout" and fb.get("fallback_layout", {}).get("champion"):
        lid = str(nid); nid += 1
        layouts[lid] = {"champion": fb["fallback_layout"].get("champion", ""),
                        "spells": fb["fallback_layout"].get("spells", []),
                        "runes": fb["fallback_layout"].get("runes", [])}
        new_fb["layout_id"] = lid
    if new_fb["mode"] == "other_roles":
        new_fb["mode"] = "random_default"
    return {"bans": cfg.get("bans", []), "layouts": layouts, "roles": roles, "fallback": new_fb}

def load_config():
    """Load config from config.json (called on every champ select for hot-reload)"""
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    if "layouts" not in cfg:
        cfg = migrate_config(cfg)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg

# Initial load to verify config exists
try:
    _cfg = load_config()
    for role, ids in _cfg.get("roles", {}).items():
        print(f"{role}: {len(ids)} picks")
    print(f"Layouts: {len(_cfg.get('layouts', {}))}")
    print(f"Bans: {len(_cfg.get('bans', []))}")
    print(f"Fallback: {_cfg.get('fallback', {}).get('mode', 'random_default')}")
    del _cfg
except Exception as e:
    print(f"Error loading config.json: {str(e)}")
    print("Please ensure config.json exists with valid configuration")
    exit(1)

# Summoner spell mappings
SUMMONER_SPELLS = {
    'barrier': 21, 'cleanse': 1, 'exhaust': 3, 'flash': 4, 'ghost': 6,
    'heal': 7, 'ignite': 14, 'smite': 11, 'teleport': 12, 'clarity': 13, 'mark': 32
}

# Rune data - will be loaded from Data Dragon
runes_data = None

# Stat rune mappings - organized by slot (will be updated from Community Dragon API)
STAT_RUNES = {
    # Offense Slot (Row 1)
    'adaptive force': 5008,  # +9 Adaptive Force
    'attack speed': 5005,    # +10% Attack Speed
    'ability haste': 5007,   # +8 Ability Haste
    
    # Flex Slot (Row 2)
    'adaptive force flex': 5008,  # +9 Adaptive Force (same as offense)
    'movement speed': 5010,       # +2% Movement Speed
    'health scaling': 5001,       # +10-180 Health (based on level)
    
    # Defense Slot (Row 3)
    'health': 5011,              # +65 Health (flat)
    'tenacity': 5013,            # +10% Tenacity and Slow Resist
    'health scaling def': 5001,  # +10-180 Health (based on level)
    
    # Legacy mappings for backward compatibility
    'armor': 5002,           # +6 Armor (removed from current system)
    'magic resist': 5003,    # +8 Magic Resist (removed from current system)
    'armor mr': 5012         # +1-8 Armor and Magic Resist (removed from current system)
}

pick_number = 0
ban_number = 0
assigned_position = ''

# Global lazy-loaded Data Dragon version
_ddragon_version = None

def get_ddragon_version():
    """Get Data Dragon version (lazy loaded)"""
    global _ddragon_version
    if _ddragon_version is None:
        _ddragon_version = requests.get('https://ddragon.leagueoflegends.com/api/versions.json').json()[0]
    return _ddragon_version

async def get_champions_map():
    # Get champion data from Data Dragon for English names
    ddragon_version = get_ddragon_version()
    ddragon_champions = requests.get(f'https://ddragon.leagueoflegends.com/cdn/{ddragon_version}/data/en_US/champion.json').json()
    # Swap key and value to map from name to ID instead
    champion_name_to_key = {name: int(champ['key']) for name, champ in ddragon_champions['data'].items()}
    
    champions_map = champion_name_to_key
            
    return champions_map

async def get_runes_data():
    """Load rune data from Data Dragon"""
    global runes_data
    try:
        ddragon_version = get_ddragon_version()
        runes_response = requests.get(f'https://ddragon.leagueoflegends.com/cdn/{ddragon_version}/data/en_US/runesReforged.json')
        runes_data = runes_response.json()
        return runes_data
    except Exception as e:
        print(f"Failed to load runes data: {str(e)}")
        return None

async def load_stat_runes():
    """Load current stat rune data from Community Dragon API with accurate slot mappings"""
    global STAT_RUNES
    try:
        response = requests.get('https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perks.json')
        perks_data = response.json()
        
        # Extract stat runes (IDs 5001-5013) with proper slot categorization
        stat_runes = {}
        for perk in perks_data:
            perk_id = perk.get('id')
            if perk_id and 5001 <= perk_id <= 5013:
                name = perk.get('name', '').lower()
                description = perk.get('shortDesc', '').lower()
                
                # Map based on actual current League stat rune system
                if perk_id == 5008:  # Adaptive Force (Offense + Flex)
                    stat_runes['adaptive force'] = perk_id
                    stat_runes['adaptive force flex'] = perk_id
                elif perk_id == 5005:  # Attack Speed (Offense)
                    stat_runes['attack speed'] = perk_id
                elif perk_id == 5007:  # Ability Haste (Offense)
                    stat_runes['ability haste'] = perk_id
                elif perk_id == 5010:  # Movement Speed (Flex)
                    stat_runes['movement speed'] = perk_id
                    stat_runes['move speed'] = perk_id
                elif perk_id == 5001:  # Health Scaling (Flex + Defense)
                    stat_runes['health scaling'] = perk_id
                    stat_runes['health scaling def'] = perk_id
                elif perk_id == 5011:  # Flat Health (Defense)
                    stat_runes['health'] = perk_id
                elif perk_id == 5013:  # Tenacity and Slow Resist (Defense)
                    stat_runes['tenacity'] = perk_id
                    stat_runes['tenacity and slow resist'] = perk_id
                
                # Legacy runes (may be removed in future updates)
                elif perk_id == 5002:  # Armor (legacy)
                    stat_runes['armor'] = perk_id
                elif perk_id == 5003:  # Magic Resist (legacy)
                    stat_runes['magic resist'] = perk_id
                elif perk_id == 5012:  # Armor and MR Scaling (legacy)
                    stat_runes['armor mr'] = perk_id
                    stat_runes['resist scaling'] = perk_id
        
        if stat_runes:
            STAT_RUNES.update(stat_runes)
            print(f"Updated stat runes from Community Dragon API: {len(stat_runes)} stat runes loaded")
            print(f"Current stat rune layout: Offense (5008/5005/5007), Flex (5008/5010/5001), Defense (5011/5013/5001)")
        
    except Exception as e:
        print(f"Failed to load stat runes from Community Dragon API: {str(e)}")
        print("Using fallback stat rune values")

def normalize_string(s):
    """Remove spaces, separators, and convert to lowercase for fuzzy matching"""
    return re.sub(r"[^a-zA-Z0-9]", "", s.lower())

def find_rune_by_name(rune_name):
    """Find rune ID by fuzzy matching the name"""
    if not runes_data:
        return None
    
    normalized_search = normalize_string(rune_name)
    
    # Search through all rune trees
    for tree in runes_data:
        # Check all slots in the tree
        for slot in tree['slots']:
            for rune in slot['runes']:
                if normalized_search in normalize_string(rune['name']):
                    return {'id': rune['id'], 'tree_id': tree['id'], 'name': rune['name']}
    
    # Check stat runes
    for stat_name, stat_id in STAT_RUNES.items():
        if normalized_search in normalize_string(stat_name):
            return {'id': stat_id, 'tree_id': None, 'name': stat_name}
    
    return None

def build_rune_page(rune_names):
    """Build a rune page from list of rune names using fuzzy matching"""
    if not rune_names or len(rune_names) == 0:
        return None
    
    selected_runes = []
    primary_tree = None
    secondary_tree = None
    
    # Process each rune name
    for i, rune_name in enumerate(rune_names):
        rune_info = find_rune_by_name(rune_name)
        if not rune_info:
            print(f"Could not find rune: {rune_name}")
            continue
            
        selected_runes.append(rune_info['id'])
        
        # Determine primary and secondary trees based on first 6 runes
        if i < 4 and rune_info['tree_id'] and not primary_tree:
            primary_tree = rune_info['tree_id']
        elif i >= 4 and i < 6 and rune_info['tree_id'] and not secondary_tree:
            secondary_tree = rune_info['tree_id']
    
    if not primary_tree:
        print("Could not determine primary rune tree")
        return None
    
    # Build the rune page data structure
    rune_page = {
        'name': 'AutoPick Runes',
        'primaryStyleId': primary_tree,
        'subStyleId': secondary_tree or 8000,  # Default to Precision if no secondary
        'selectedPerkIds': selected_runes,
        'current': True
    }
    
    return rune_page

DEFAULT_SPELLS = {
    'TOP': ['flash', 'teleport'],
    'JUNGLE': ['flash', 'smite'],
    'MIDDLE': ['flash', 'ignite'],
    'BOTTOM': ['flash', 'heal'],
    'UTILITY': ['flash', 'exhaust']
}

def get_role_champions(assigned_position, config):
    """Get champion list for assigned role with configurable fallback.

    Config uses layouts+roles format:
      layouts: {id: {champion, spells, runes}}
      roles: {role: [layout_ids]}
      fallback: {mode, layout_id}
    """
    role_mapping = {
        'TOP': 'top',
        'JUNGLE': 'jungle',
        'MIDDLE': 'mid',
        'BOTTOM': 'bot',
        'UTILITY': 'utility'
    }

    role_key = role_mapping.get(assigned_position, 'mid')
    layouts = config.get("layouts", {})
    roles = config.get("roles", {})
    fallback = config.get("fallback", {"mode": "random_default", "layout_id": ""})

    # Get layout IDs for this role
    role_ids = roles.get(role_key, [])
    if role_ids:
        # Resolve layout IDs to actual layout dicts
        result = []
        for lid in role_ids:
            layout = layouts.get(lid)
            if layout:
                result.append(layout)
        if result:
            return result

    # No layouts for this role - use fallback
    fallback_mode = fallback.get('mode', 'random_default')

    if fallback_mode == 'fallback_layout':
        fb_lid = fallback.get('layout_id', '')
        if fb_lid and fb_lid in layouts:
            return [layouts[fb_lid]]

    # Default: random champion + default runes
    return [{'champion': '__RANDOM__', 'spells': [], 'runes': []}]

async def set_recommended_runes(connection, champion_id, position):
    """Try to set recommended runes from the LCU for a champion"""
    try:
        pages_response = await connection.request('get', '/lol-perks/v1/recommended-pages')
        if hasattr(pages_response, 'json'):
            pages = await pages_response.json()
        else:
            pages = pages_response

        if not isinstance(pages, list) or not pages:
            return

        # Find page matching champion and position
        best_page = None
        for page in pages:
            if page.get('championId') == champion_id:
                if page.get('position', '').upper() == position:
                    best_page = page
                    break
                elif not best_page:
                    best_page = page

        if not best_page and pages:
            best_page = pages[0]

        if best_page:
            rune_page = {
                'name': 'AutoPick Runes',
                'primaryStyleId': best_page.get('primaryPerkStyleId', best_page.get('primaryStyleId')),
                'subStyleId': best_page.get('secondaryPerkStyleId', best_page.get('subStyleId')),
                'selectedPerkIds': best_page.get('perkIds', best_page.get('selectedPerkIds', [])),
                'current': True
            }

            current_pages = await connection.request('get', '/lol-perks/v1/pages')
            if hasattr(current_pages, 'json'):
                current_pages = await current_pages.json()

            for page in current_pages:
                if page.get('name') == 'AutoPick Runes' and page.get('isDeletable', True):
                    await connection.request('delete', f'/lol-perks/v1/pages/{page["id"]}')
                    break

            await connection.request('post', '/lol-perks/v1/pages', data=rune_page)
            print(f"Set recommended runes for champion {champion_id}")
    except Exception as e:
        print(f"Could not set recommended runes: {str(e)}")

async def get_owned_champion_ids(connection):
    """Fetch the set of champion IDs the logged-in account owns (LCU 'lol-champions' plugin,
    undocumented but community-verified: https://swagger.dysolix.dev/lcu/ -> owned-champions-minimal).
    Returns None on failure so caller can decide to retry rather than treat as "owns nothing"."""
    try:
        resp = await connection.request('get', '/lol-champions/v1/owned-champions-minimal')
        if hasattr(resp, 'status') and resp.status != 200:
            print(f"owned-champions-minimal returned status {resp.status}")
            return None
        champs = await resp.json() if hasattr(resp, 'json') else resp
        if not isinstance(champs, list):
            return None
        return {c['id'] for c in champs if c.get('id')}
    except Exception as e:
        print(f"Failed to fetch owned champions: {str(e)}")
        return None

@connector.ready
async def connect(connection):
    global champions_map, runes_data, owned_champion_ids
    champions_map = await get_champions_map()
    runes_data = await get_runes_data()
    await load_stat_runes()
    owned_champion_ids = await get_owned_champion_ids(connection)
    print(f"Owned champions: {len(owned_champion_ids) if owned_champion_ids else 'unknown (fetch failed)'}")

@connector.ws.register('/lol-matchmaking/v1/ready-check', event_types=('UPDATE',))
async def ready_check_changed(connection, event):
    global have_i_prepicked
    if event.data['state'] == 'InProgress' and event.data['playerResponse'] == 'None':
        await connection.request('post', '/lol-matchmaking/v1/ready-check/accept', data={})
        # Reset prepick status when accepting a new queue
        have_i_prepicked = False
        print("Queue accepted, reset prepick status")


@connector.ws.register('/lol-champ-select/v1/session', event_types=('CREATE', 'UPDATE',))
async def champ_select_changed(connection, event):
    global am_i_assigned, pick_number, ban_number, am_i_banning, am_i_picking, phase, in_game, action_id, have_i_prepicked, assigned_position

    # Hot-reload config on every champ select event
    try:
        config = load_config()
        bans = config.get("bans", [])
    except Exception as e:
        print(f"Config reload failed, using defaults: {e}")
        return

    lobby_phase = event.data['timer']['phase']

    local_player_cell_id = event.data['localPlayerCellId']
    for teammate in event.data['myTeam']:
        if teammate['cellId'] == local_player_cell_id:
            assigned_position = teammate['assignedPosition']
            am_i_assigned = True

    print(f'Assigned position: {assigned_position}')

    # Get list of banned champions
    banned_champions = []
    for action_list in event.data['actions']:
        for action in action_list:
            if action['type'] == 'ban' and action['completed']:
                banned_champions.append(action['championId'])

    for action in event.data['actions']:
        for actionArr in action:
            if actionArr['actorCellId'] == local_player_cell_id and actionArr['isInProgress'] == True:
                phase = actionArr['type']
                action_id = actionArr['id']
                if phase == 'ban':
                    am_i_banning = actionArr['isInProgress']
                if phase == 'pick':
                    am_i_picking = actionArr['isInProgress']

    if phase == 'ban' and lobby_phase == 'BAN_PICK' and am_i_banning:
        while am_i_banning and ban_number < len(bans):
            try:
                await connection.request('patch', '/lol-champ-select/v1/session/actions/%d' % action_id,
                                         data={"championId": champions_map[bans[ban_number]], "completed": True})
                print(f"Successfully banned {bans[ban_number]}")
                break
            except Exception as e:
                print(f"Failed to ban {bans[ban_number]}: {str(e)}")
                print(f"Full error: {traceback.format_exc()}")
                ban_number += 1
                if ban_number >= len(bans):
                    pick_number = 0
        ban_number = 0
        am_i_banning = False

    if phase == 'pick' and lobby_phase == 'BAN_PICK' and am_i_picking:
        role_champions = get_role_champions(assigned_position, config)
        is_random = False
        random_retries = 0
        while am_i_picking and pick_number < len(role_champions):
            try:
                pick_data = parse_pick_entry(role_champions[pick_number])

                # Handle random fallback
                if pick_data['champion'] == '__RANDOM__':
                    is_random = True
                    available = [name for name, cid in champions_map.items() if cid not in banned_champions]
                    if not available:
                        break
                    pick_data['champion'] = random.choice(available)
                    pick_data['spells'] = DEFAULT_SPELLS.get(assigned_position, ['flash', 'ignite'])
                    pick_data['runes'] = []

                champion_id = champions_map.get(pick_data['champion'])

                if not champion_id:
                    print(f"Champion {pick_data['champion']} not found, trying next pick")
                    pick_number += 1
                    continue

                if champion_id in banned_champions:
                    print(f"{pick_data['champion']} is banned, trying next pick")
                    pick_number += 1
                    continue

                if not is_random and owned_champion_ids is not None and champion_id not in owned_champion_ids:
                    print(f"{pick_data['champion']} not owned, trying next pick")
                    pick_number += 1
                    continue

                resp = await connection.request('patch', '/lol-champ-select/v1/session/actions/%d' % action_id,
                                         data={"championId": champion_id, "completed": True})
                if hasattr(resp, 'status') and resp.status >= 400:
                    body = await resp.text() if hasattr(resp, 'text') else ''
                    raise Exception(f"LCU rejected pick (status {resp.status}): {body}")
                print(f"Successfully picked {pick_data['champion']} for {assigned_position}")

                # Set summoner spells
                if pick_data['spells']:
                    await set_summoner_spells(connection, pick_data['spells'])

                # Set runes - use recommended for random picks, config for explicit
                if pick_data['runes']:
                    await set_runes(connection, pick_data['runes'])
                elif is_random:
                    await set_recommended_runes(connection, champion_id, assigned_position)

                break
            except Exception as e:
                print(f"Failed to pick: {str(e)}")
                print(f"Full error: {traceback.format_exc()}")
                if is_random:
                    random_retries += 1
                    if random_retries >= 5:
                        break
                    continue
                pick_number += 1
                if pick_number >= len(role_champions):
                    pick_number = 0
        pick_number = 0
        am_i_picking = False

    if lobby_phase == 'PLANNING' and not have_i_prepicked:
        pick_action_id = None
        for action_list in event.data['actions']:
            for action in action_list:
                if action['actorCellId'] == local_player_cell_id and action['type'] == 'pick':
                    pick_action_id = action['id']
                    break

        if pick_action_id:
            try:
                role_champions = get_role_champions(assigned_position, config)
                for entry in role_champions:
                    pick_data = parse_pick_entry(entry)
                    is_random = pick_data['champion'] == '__RANDOM__'

                    # Handle random for pre-pick
                    if is_random:
                        available = list(champions_map.keys())
                        if not available:
                            continue
                        pick_data['champion'] = random.choice(available)
                        pick_data['spells'] = DEFAULT_SPELLS.get(assigned_position, ['flash', 'ignite'])

                    champion_id = champions_map.get(pick_data['champion'])
                    if not champion_id:
                        continue

                    if not is_random and owned_champion_ids is not None and champion_id not in owned_champion_ids:
                        print(f"Skipping pre-pick, {pick_data['champion']} not owned, trying next")
                        continue

                    resp = await connection.request('patch', f'/lol-champ-select/v1/session/actions/{pick_action_id}',
                                             data={"championId": champion_id, "completed": False})
                    if hasattr(resp, 'status') and resp.status >= 400:
                        body = await resp.text() if hasattr(resp, 'text') else ''
                        print(f"LCU rejected pre-pick {pick_data['champion']} (status {resp.status}): {body}, trying next")
                        continue

                    print(f"Pre-picked {pick_data['champion']} for {assigned_position}")
                    have_i_prepicked = True

                    if pick_data['spells']:
                        await set_summoner_spells(connection, pick_data['spells'])

                    if pick_data['runes']:
                        await set_runes(connection, pick_data['runes'])
                    break
            except Exception as e:
                print(f"Failed to pre-pick: {str(e)}")
                print(f"Full error: {traceback.format_exc()}")

    if lobby_phase == 'FINALIZATION':
        try:
            game_state = await connection.request('get', '/lol-gameflow/v1/gameflow-phase')
            if game_state == 'InGame' and not in_game:
                print("Game started! Continuing to monitor for next champion select...")
                in_game = True
            await asyncio.sleep(2)
        except Exception as e:
            print('Waiting for game to start...')
            print(f"Error checking game state: {str(e)}")
            await asyncio.sleep(2)


def parse_pick_entry(pick_entry):
    """Parse a pick entry that can be either a string or dict with champion, spells, and runes"""
    if isinstance(pick_entry, str):
        return {'champion': pick_entry, 'spells': [], 'runes': []}
    elif isinstance(pick_entry, dict):
        champion = pick_entry.get('champion', '')
        spells = pick_entry.get('spells', [])
        runes = pick_entry.get('runes', [])
        # Normalize spell names to lowercase
        normalized_spells = [spell.lower() for spell in spells] if spells else []
        return {'champion': champion, 'spells': normalized_spells, 'runes': runes}
    else:
        return {'champion': '', 'spells': [], 'runes': []}

async def set_summoner_spells(connection, spells):
    """Set summoner spells using the my-selection endpoint"""
    if not spells or len(spells) == 0:
        return
    
    try:
        spell_ids = []
        for spell in spells:
            spell_id = SUMMONER_SPELLS.get(spell.lower())
            if spell_id:
                spell_ids.append(spell_id)
            else:
                print(f"Unknown summoner spell: {spell}")
        
        if len(spell_ids) == 1:
            # Only one spell specified, set it as spell1, keep spell2 unchanged
            data = {"spell1Id": spell_ids[0]}
        elif len(spell_ids) >= 2:
            # Two spells specified
            data = {"spell1Id": spell_ids[0], "spell2Id": spell_ids[1]}
        else:
            return
        
        await connection.request('patch', '/lol-champ-select/v1/session/my-selection', data=data)
        spell_names = [spell for spell in spells if spell.lower() in SUMMONER_SPELLS]
        print(f"Set summoner spells: {', '.join(spell_names)}")
        
    except Exception as e:
        print(f"Failed to set summoner spells {spells}: {str(e)}")
        print(f"Full error: {traceback.format_exc()}")

async def set_runes(connection, rune_names):
    """Set runes by creating/replacing a rune page"""
    if not rune_names or len(rune_names) == 0:
        return
    
    try:
        # Build rune page from names
        rune_page_data = build_rune_page(rune_names)
        if not rune_page_data:
            print("Failed to build rune page")
            return
        
        # Get current rune pages to find one to replace
        pages_response = await connection.request('get', '/lol-perks/v1/pages')
        if hasattr(pages_response, 'json'):
            current_pages = await pages_response.json()
        else:
            current_pages = pages_response
        
        # Delete the oldest editable page if we have too many, or find an AutoPick page to replace
        page_to_replace = None
        for page in current_pages:
            if not page.get('isDeletable', True):
                continue
            if page.get('name') == 'AutoPick Runes':
                page_to_replace = page
                break
        
        # If no AutoPick page found, replace oldest editable page
        if not page_to_replace:
            editable_pages = [p for p in current_pages if p.get('isDeletable', True)]
            if editable_pages:
                page_to_replace = editable_pages[0]  # Replace first editable page
        
        # Delete the page to replace
        if page_to_replace:
            await connection.request('delete', f'/lol-perks/v1/pages/{page_to_replace["id"]}')
        
        # Create new rune page
        await connection.request('post', '/lol-perks/v1/pages', data=rune_page_data)
        print(f"Set runes: {rune_page_data['name']}")
        
    except Exception as e:
        print(f"Failed to set runes: {str(e)}")
        print(f"Full error: {traceback.format_exc()}")

@connector.close
async def disconnect(_):
    print('The client has been closed!')


connector.start()