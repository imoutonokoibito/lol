import asyncio
import time
import requests
import urllib3
import traceback
import json
import re
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

# Load config from config.json
try:
    with open("config.json", "r") as f:
        config = json.load(f)
    champions_config = config.get("champions", {})
    bans = config.get("bans", [])
    # Print configuration summary
    for role, config in champions_config.items():
        pick_count = len(config.get("order", []))
        print(f"{role}: {pick_count} picks")
    print(f"Bans: {len(bans)}")
    if not champions_config or not bans:
        raise ValueError("Champions or bans configuration is missing in config.json")
except Exception as e:
    print(f"Error loading config.json: {str(e)}")
    print("Please ensure config.json exists with valid champions and bans configuration")
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

def get_role_champions(assigned_position):
    """Get champion list for assigned role with fallback to other roles"""
    role_mapping = {
        'TOP': 'top',
        'JUNGLE': 'jungle', 
        'MIDDLE': 'mid',
        'BOTTOM': 'bot',
        'UTILITY': 'utility'
    }
    
    role_key = role_mapping.get(assigned_position, 'mid')
    role_order = ['top', 'jungle', 'mid', 'bot', 'utility']
    
    # Try assigned role first, then fallback to other roles
    for role in [role_key] + [r for r in role_order if r != role_key]:
        if role in champions_config and 'order' in champions_config[role]:
            champions = champions_config[role]['order']
            if champions:
                return champions
    
    return []

@connector.ready
async def connect(connection):
    global champions_map, runes_data
    champions_map = await get_champions_map()
    runes_data = await get_runes_data()
    await load_stat_runes()

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
    global am_i_assigned, pick_number, ban_number, am_i_banning, am_i_picking, phase, bans, in_game, action_id, have_i_prepicked, assigned_position
    
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
        ban_number = 0  # Reset ban number after successful ban
        am_i_banning = False

    if phase == 'pick' and lobby_phase == 'BAN_PICK' and am_i_picking:
        role_champions = get_role_champions(assigned_position)
        while am_i_picking and pick_number < len(role_champions):
            try:
                pick_data = parse_pick_entry(role_champions[pick_number])
                champion_id = champions_map.get(pick_data['champion'])
                
                if not champion_id:
                    print(f"Champion {pick_data['champion']} not found, trying next pick")
                    pick_number += 1
                    continue
                    
                if champion_id in banned_champions:
                    print(f"{pick_data['champion']} is banned, trying next pick")
                    pick_number += 1
                    continue
                
                await connection.request('patch', '/lol-champ-select/v1/session/actions/%d' % action_id,
                                         data={"championId": champion_id, "completed": True})
                print(f"Successfully picked {pick_data['champion']} for {assigned_position}")
                
                # Set summoner spells if specified
                if pick_data['spells']:
                    await set_summoner_spells(connection, pick_data['spells'])
                
                # Set runes if specified
                if pick_data['runes']:
                    await set_runes(connection, pick_data['runes'])
                
                break
            except Exception as e:
                print(f"Failed to pick {role_champions[pick_number]}: {str(e)}")
                print(f"Full error: {traceback.format_exc()}")
                pick_number += 1
                if pick_number >= len(role_champions):
                    pick_number = 0
        pick_number = 0
        am_i_picking = False

    if lobby_phase == 'PLANNING' and not have_i_prepicked:
        # Find the pick action for pre-picking
        pick_action_id = None
        for action_list in event.data['actions']:
            for action in action_list:
                if action['actorCellId'] == local_player_cell_id and action['type'] == 'pick':
                    pick_action_id = action['id']
                    break
        
        if pick_action_id:
            try:
                role_champions = get_role_champions(assigned_position)
                pick_data = parse_pick_entry(role_champions[0]) if role_champions else None
                if pick_data:
                    champion_id = champions_map.get(pick_data['champion'])
                    if champion_id:
                        await connection.request('patch', f'/lol-champ-select/v1/session/actions/{pick_action_id}',
                                                 data={"championId": champion_id, "completed": False})
                        print(f"Pre-picked {pick_data['champion']} for {assigned_position}")
                        have_i_prepicked = True
                        
                        # Set summoner spells if specified
                        if pick_data['spells']:
                            await set_summoner_spells(connection, pick_data['spells'])
                            
                        # Set runes if specified
                        if pick_data['runes']:
                            await set_runes(connection, pick_data['runes'])
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