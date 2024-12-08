import asyncio
import time
import requests
import urllib3
import traceback
import toml
from lcu_driver import Connector

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

connector = Connector()
global am_i_assigned, am_i_picking, am_i_banning, ban_number, phase, picks, bans, in_game
am_i_assigned = False
am_i_banning = False
am_i_picking = False
in_game = False
phase = ''

# Load picks and bans from config.toml
try:
    config = toml.load("config.toml")
    picks = config.get("picks", [])
    bans = config.get("bans", [])
    if not picks or not bans:
        raise ValueError("Picks or bans list is empty in config.toml")
except Exception as e:
    print(f"Error loading config.toml: {str(e)}")
    print("Please ensure config.toml exists with valid picks and bans lists")
    exit(1)

pick_number = 0
ban_number = 0


async def get_champions_map():
    # Get champion data from Data Dragon for English names
    ddragon_version = requests.get('https://ddragon.leagueoflegends.com/api/versions.json').json()[0]
    ddragon_champions = requests.get(f'https://ddragon.leagueoflegends.com/cdn/{ddragon_version}/data/en_US/champion.json').json()
    # Swap key and value to map from name to ID instead
    champion_name_to_key = {name: int(champ['key']) for name, champ in ddragon_champions['data'].items()}
    
    champions_map = champion_name_to_key

    print(f"{len(champions_map)=}", f"{champions_map=}")
            
    return champions_map

@connector.ready
async def connect(connection):
    global champions_map
    champions_map = await get_champions_map()

@connector.ws.register('/lol-matchmaking/v1/ready-check', event_types=('UPDATE',))
async def ready_check_changed(connection, event):
    if event.data['state'] == 'InProgress' and event.data['playerResponse'] == 'None':
        await connection.request('post', '/lol-matchmaking/v1/ready-check/accept', data={})


@connector.ws.register('/lol-champ-select/v1/session', event_types=('CREATE', 'UPDATE',))
async def champ_select_changed(connection, event):
    global am_i_assigned, pick_number, ban_number, am_i_banning, am_i_picking, phase, bans, picks, have_i_prepicked, in_game, action_id
    have_i_prepicked = False
    lobby_phase = event.data['timer']['phase']

    local_player_cell_id = event.data['localPlayerCellId']
    for teammate in event.data['myTeam']:
        if teammate['cellId'] == local_player_cell_id:
            assigned_position = teammate['assignedPosition']
            am_i_assigned = True

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
        while am_i_banning:
            try:
                await connection.request('patch', '/lol-champ-select/v1/session/actions/%d' % action_id,
                                         data={"championId": champions_map[bans[ban_number]], "completed": True})
                print(f"Successfully banned {bans[ban_number]}")
                ban_number += 1
                am_i_banning = False
            except Exception as e:
                print(f"Failed to ban {bans[ban_number]}: {str(e)}")
                print(f"Full error: {traceback.format_exc()}")
                ban_number += 1
                if ban_number >= len(bans):
                    print("Exhausted all ban options, stopping ban attempts")
                    am_i_banning = False
                    break

    if phase == 'pick' and lobby_phase == 'BAN_PICK' and am_i_picking:
        while am_i_picking:
            print(f"{champions_map=}")
            try:
                await connection.request('patch', '/lol-champ-select/v1/session/actions/%d' % action_id,
                                         data={"championId": champions_map[picks[pick_number]], "completed": True})
                print(f"Successfully picked {picks[pick_number]}")
                am_i_picking = False
            except Exception as e:
                print(f"Failed to pick {picks[pick_number]}: {str(e)}")
                print(f"Full error: {traceback.format_exc()}")
                pick_number += 1
                if pick_number >= len(picks):
                    print("Exhausted all pick options, stopping pick attempts")
                    am_i_picking = False
                    break

    if lobby_phase == 'PLANNING' and not have_i_prepicked:
        try:
            await connection.request('patch', '/lol-champ-select/v1/session/actions/%d' % action_id,
                                     data={"championId": champions_map[picks[0]], "completed": False})
            print(f"Pre-picked {picks[0]}")
            have_i_prepicked = True
        except Exception as e:
            print(f"Failed to pre-pick {picks[0]}: {str(e)}")
            print(f"Full error: {traceback.format_exc()}")

    if lobby_phase == 'FINALIZATION':
        try:
            request_game_data = requests.get('https://127.0.0.1:2999/liveclientdata/allgamedata', verify=False)
            game_data = request_game_data.json()['gameData']['gameTime']
            if game_data > 0 and not in_game:
                print("Game started! Exiting champion select bot...")
                in_game = True
                exit(69)
            await asyncio.sleep(2)
        except Exception as e:
            print('Waiting for game to start...')
            print(f"Game data request error: {str(e)}")
            await asyncio.sleep(2)


@connector.close
async def disconnect(_):
    print('The client has been closed!')


connector.start()