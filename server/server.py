# COREMASTER - core for Florest's Counter-strike.
# CoreMaster is a core with supporting of full packets' manage with plugins.
# Please don't install plugins with obfuscation! It can be dangerous.

import asyncio, orjson, time, os, pathlib, sys, importlib.util, random
import math, base64
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes

path = pathlib.Path(sys.argv[0]).parent.resolve()
plugins_path = path / 'plugins'
if not os.path.exists(plugins_path): os.mkdir(plugins_path)
if not os.path.exists(path / 'approved_plugins.txt'):
    with open(path / 'approved_plugins.txt', 'w') as f:
        pass

PLAYER_COLORS = ["red", "green", "blue", "yellow", "purple", "orange", "white", "black"]

# --- КРИПТОГРАФИЯ ---
class ClientCrypto:
    def __init__(self):
        self.server_private_key = x25519.X25519PrivateKey.generate()
        self.server_public_key = self.server_private_key.public_key()
        self.client_keys = {}
        self.client_send_nonce = {}
        self.client_recv_nonce = {}
    
    def get_public_key_bytes(self):
        return self.server_public_key.public_bytes_raw()
    
    def handshake_client(self, addr_str, client_public_bytes):
        try:
            client_public_key = x25519.X25519PublicKey.from_public_bytes(client_public_bytes)
            shared_secret = self.server_private_key.exchange(client_public_key)
            
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=b'coremaster-game-encryption'
            )
            session_key = hkdf.derive(shared_secret)
            
            self.client_keys[addr_str] = session_key
            self.client_send_nonce[addr_str] = 0
            self.client_recv_nonce[addr_str] = 0
            return True
        except Exception as e:
            print(f"[CRYPTO] Handshake failed for {addr_str}: {e}")
            return False
    
    def encrypt_packet(self, addr_str, data: bytes) -> bytes:
        if addr_str not in self.client_keys:
            return data
        try:
            aesgcm = AESGCM(self.client_keys[addr_str])
            nonce = self.client_send_nonce[addr_str].to_bytes(12, 'big')
            encrypted = aesgcm.encrypt(nonce, data, None)
            self.client_send_nonce[addr_str] += 1
            return encrypted
        except Exception as e:
            print(f"[CRYPTO] Encryption error: {e}")
            return data
    
    def decrypt_packet(self, addr_str, encrypted_data: bytes) -> bytes:
        if addr_str not in self.client_keys:
            return encrypted_data
        
        for offset in range(4):
            try:
                aesgcm = AESGCM(self.client_keys[addr_str])
                nonce = (self.client_recv_nonce[addr_str] + offset).to_bytes(12, 'big')
                decrypted = aesgcm.decrypt(nonce, encrypted_data, None)
                self.client_recv_nonce[addr_str] += offset + 1
                return decrypted
            except:
                continue
        return None

# --- ТИПЫ БЛОКОВ ---
BLOCK_TYPES = {
    "stone": {"name": "Камень", "color": "gray", "hp": 150, "destructible": True},
    "brick": {"name": "Кирпич", "color": "red", "hp": 120, "destructible": True},
    "wood": {"name": "Дерево", "color": "brown", "hp": 80, "destructible": True},
    "bedrock": {"name": "Коренная порода", "color": "black", "hp": 999999, "destructible": False}
}

BUILD_DISTANCE = 5.0

class GameServer(asyncio.DatagramProtocol):
    def __init__(self):
        self.players = {}
        self.clients = {}
        self.last_seen = {}
        self.chat = []
        self.pending_shots = []
        self.start_time = time.time()
        self.running = True
        
        self.crypto = ClientCrypto()
        
        self.tnt_entities = []
        self.map_blocks = []
        
        self.player_inventory = {}
        self.build_mode = {}
        
        self.map_data = [
            {"pos": [5, 1, 5], "scale": [2, 2, 2], "type": "stone", "destructible": True, "id": "block1", "hp": 150},
            {"pos": [-10, 3, 10], "scale": [4, 6, 4], "type": "brick", "destructible": True, "id": "block2", "hp": 120},
            {"pos": [0, 1, -15], "scale": [10, 2, 2], "type": "stone", "destructible": True, "id": "block3", "hp": 150},
        ]
        self.map_blocks = self.map_data.copy()
        
        # События для плагинов
        self.events = {
            "on_raw_packet": [],      # ПЛАГИНЫ ВИДЯТ RAW ДАННЫЕ
            "on_decrypted_packet": [], # ПОСЛЕ РАСШИФРОВКИ
            "on_join": [],
            "on_death": [],
            "on_chat": [],
            "on_tick": [],
            "on_stop": [],
            "on_explosion": [],
            "on_build": [],
            "on_block_destroy": []
        }

    def say(self, message):
        msg = f"[SERVER]: {message}"
        self.chat.append(msg)
        if len(self.chat) > 8:
            self.chat.pop(0)
        print(f"[CHAT] {msg}")

    async def stop(self):
        self.trigger("on_stop")
        await asyncio.sleep(1.5)
        os._exit(0)

    def get_approved_plugins(self):
        try:
            with open(path / 'approved_plugins.txt', 'r') as f:
                return [line.strip() for line in f.readlines()]
        except FileNotFoundError:
            return []
    
    def new_approved_plugin(self, name):
        with open(path / 'approved_plugins.txt', 'a') as f:
            f.write(f'{name}\n')

    def load_plugins(self):
        print("[CoreMaster] Loading plugins...")
        plugins = 0
        for plugin_file in plugins_path.glob('*.py'):
            try:
                module_name = f"plugins.{plugin_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, plugin_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if hasattr(module, 'CoreMasterPlugin'):
                    if not hasattr(module, 'annotations'):
                        print(f'[CoreMaster] {plugin_file.stem} no annotations')
                        continue
                    plugin = module.CoreMasterPlugin(self)
                    if hasattr(plugin, 'on_enable'):
                        plugin.on_enable()
                    print(f"[CoreMaster] Plugin '{plugin_file.stem}' loaded")
                    plugins += 1
            except Exception as e:
                print(f"[CoreMaster] Plugin error {plugin_file.stem}: {e}")
        print(f"[CoreMaster] {plugins} plugins loaded")

    def register_event(self, event_name, func):
        if event_name in self.events:
            self.events[event_name].append(func)

    def trigger(self, event_name, *args):
        for func in self.events.get(event_name, []):
            try:
                if asyncio.iscoroutinefunction(func):
                    asyncio.create_task(func(*args))
                else:
                    func(*args)
            except Exception as e:
                print(f"[CoreMaster] Plugin error in {event_name}: {e}")

    def can_build(self, player_addr, block_pos):
        if player_addr not in self.players:
            return False
        player = self.players[player_addr]
        dx = block_pos[0] - player["x"]
        dy = block_pos[1] - player["y"]
        dz = block_pos[2] - player["z"]
        if math.sqrt(dx*dx + dy*dy + dz*dz) > BUILD_DISTANCE:
            return False
        for block in self.map_blocks:
            if (abs(block["pos"][0] - block_pos[0]) < 0.5 and
                abs(block["pos"][1] - block_pos[1]) < 0.5 and
                abs(block["pos"][2] - block_pos[2]) < 0.5):
                return False
        for p_data in self.players.values():
            if (abs(p_data["x"] - block_pos[0]) < 0.8 and
                abs(p_data["y"] - block_pos[1]) < 0.8 and
                abs(p_data["z"] - block_pos[2]) < 0.8):
                return False
        return True

    def place_block(self, player_addr, block_type, pos):
        if not self.can_build(player_addr, pos):
            return False
        if self.build_mode.get(player_addr) == "survival":
            if player_addr not in self.player_inventory:
                self.player_inventory[player_addr] = {"stone": 0, "brick": 0, "wood": 0}
            if self.player_inventory[player_addr].get(block_type, 0) <= 0:
                self.say(f"Нет {BLOCK_TYPES[block_type]['name']}!")
                return False
            self.player_inventory[player_addr][block_type] -= 1
        
        block_id = f"block_{time.time()}_{random.randint(1000, 9999)}"
        new_block = {
            "pos": pos, "scale": [1, 1, 1],
            "type": block_type, "destructible": BLOCK_TYPES[block_type]["destructible"],
            "id": block_id, "hp": BLOCK_TYPES[block_type]["hp"],
            "owner": self.players[player_addr]["n"]
        }
        self.map_blocks.append(new_block)
        self.trigger("on_build", player_addr, block_type, pos)
        self.say(f"{self.players[player_addr]['n']} построил {BLOCK_TYPES[block_type]['name']}!")
        return True

    def break_block(self, player_addr, block_pos):
        for i, block in enumerate(self.map_blocks):
            if (abs(block["pos"][0] - block_pos[0]) < 0.5 and
                abs(block["pos"][1] - block_pos[1]) < 0.5 and
                abs(block["pos"][2] - block_pos[2]) < 0.5):
                
                if not block.get("destructible", True):
                    self.say("Этот блок нельзя сломать!")
                    return False
                
                player = self.players[player_addr]
                dx = block_pos[0] - player["x"]
                dy = block_pos[1] - player["y"]
                dz = block_pos[2] - player["z"]
                if math.sqrt(dx*dx + dy*dy + dz*dz) > BUILD_DISTANCE:
                    return False
                
                if self.build_mode.get(player_addr) == "survival" and "type" in block:
                    block_type = block["type"]
                    if player_addr not in self.player_inventory:
                        self.player_inventory[player_addr] = {"stone": 0, "brick": 0, "wood": 0}
                    if block_type in self.player_inventory[player_addr]:
                        self.player_inventory[player_addr][block_type] += 1
                        self.say(f"{self.players[player_addr]['n']} получил {BLOCK_TYPES[block_type]['name']}!")
                
                removed = self.map_blocks.pop(i)
                self.trigger("on_block_destroy", player_addr, removed)
                return True
        return False

    def explode(self, tnt):
        if not tnt["active"]:
            return
        x, y, z = tnt["pos"]
        radius = 5.0
        self.say(f"💥 BOOM at ({x:.1f}, {y:.1f}, {z:.1f})!")
        
        players_hit = []
        for addr, p_data in self.players.items():
            if p_data["hp"] <= 0:
                continue
            dx = p_data["x"] - x
            dy = p_data["y"] - y
            dz = p_data["z"] - z
            distance = math.sqrt(dx*dx + dy*dy + dz*dz)
            if distance <= radius:
                damage = int(5 * (1 - distance/radius) + 1)
                p_data["hp"] -= damage
                players_hit.append({"name": p_data["n"], "damage": damage})
                if p_data["hp"] <= 0:
                    self.say(f"{p_data['n']} was blown up!")
                    self.trigger("on_death", p_data["n"], "TNT")
        
        destroyed_blocks = []
        blocks_to_remove = []
        for block in self.map_blocks:
            if not block.get("destructible", False):
                continue
            bx, by, bz = block["pos"]
            dx = bx - x
            dy = by - y
            dz = bz - z
            if math.sqrt(dx*dx + dy*dy + dz*dz) <= radius:
                blocks_to_remove.append(block)
                destroyed_blocks.append(block)
        
        for block in blocks_to_remove:
            if block in self.map_blocks:
                self.map_blocks.remove(block)
        
        explosion_data = {"explosion": {"pos": [x, y, z], "radius": radius, "destroyed_blocks": [b.get("id") for b in destroyed_blocks], "players_hit": players_hit}}
        for addr_str, c_addr in self.clients.items():
            encrypted = self.crypto.encrypt_packet(addr_str, orjson.dumps(explosion_data))
            self.transport.sendto(encrypted, c_addr)
        
        self.trigger("on_explosion", x, y, z, radius, destroyed_blocks, players_hit)
        tnt["active"] = False

    def spawn_tnt(self, x, y, z, fuse=3.0):
        tnt_id = f"tnt_{time.time()}_{random.randint(1000, 9999)}"
        tnt = {"id": tnt_id, "pos": [x, y, z], "fuse": fuse, "spawn_time": time.time(), "active": True}
        self.tnt_entities.append(tnt)
        tnt_data = {"tnt_spawn": {"id": tnt_id, "pos": [x, y, z], "fuse": fuse}}
        for addr_str, c_addr in self.clients.items():
            encrypted = self.crypto.encrypt_packet(addr_str, orjson.dumps(tnt_data))
            self.transport.sendto(encrypted, c_addr)
        self.say(f"💣 TNT spawned at ({x:.1f}, {y:.1f}, {z:.1f})!")

    def connection_made(self, transport):
        self.transport = transport
        print("[CoreMaster] UDP server started on port 9999")
        self.load_plugins()
        asyncio.create_task(self.game_loop())
        asyncio.create_task(self.tnt_tick())

    async def tnt_tick(self):
        while self.running:
            await asyncio.sleep(0.1)
            now = time.time()
            exploded = []
            for tnt in self.tnt_entities:
                if tnt["active"] and now - tnt["spawn_time"] >= tnt["fuse"]:
                    self.explode(tnt)
                    exploded.append(tnt)
            for tnt in exploded:
                if tnt in self.tnt_entities:
                    self.tnt_entities.remove(tnt)

    async def game_loop(self):
        while self.running:
            await asyncio.sleep(0.05)
            now = time.time()
            to_del = [a for a, lt in self.last_seen.items() if now - lt > 5]
            for a in to_del:
                if a in self.players:
                    name = self.players[a]['n']
                    del self.players[a], self.clients[a], self.last_seen[a]
                    if a in self.player_inventory:
                        del self.player_inventory[a]
                    if a in self.build_mode:
                        del self.build_mode[a]
                    if a in self.crypto.client_keys:
                        del self.crypto.client_keys[a]
                        del self.crypto.client_send_nonce[a]
                        del self.crypto.client_recv_nonce[a]
                    self.say(f"{name} left.")
            self.trigger("on_tick", now)
            if not self.clients:
                continue
            world_state = orjson.dumps({
                "players": list(self.players.values()),
                "chat": self.chat,
                "shots": self.pending_shots,
                "map": self.map_blocks,
                "tnt_active": [{"id": t["id"], "pos": t["pos"]} for t in self.tnt_entities if t["active"]],
                "block_types": BLOCK_TYPES
            })
            for addr_str, c_addr in self.clients.items():
                encrypted = self.crypto.encrypt_packet(addr_str, world_state)
                self.transport.sendto(encrypted, c_addr)
            self.pending_shots = []

    def datagram_received(self, data, addr):
        try:
            addr_str = f"{addr[0]}:{addr[1]}"
            
            # 1. ПЛАГИНЫ ПОЛУЧАЮТ RAW ДАННЫЕ (зашифрованные или нет)
            self.trigger("on_raw_packet", addr_str, data)
            
            # 2. Расшифровываем
            if addr_str in self.crypto.client_keys:
                decrypted = self.crypto.decrypt_packet(addr_str, data)
                if decrypted is None:
                    return
                msg = orjson.loads(decrypted)
            else:
                try:
                    msg = orjson.loads(data)
                except:
                    if len(data) == 32:
                        if self.crypto.handshake_client(addr_str, data):
                            self.transport.sendto(self.crypto.get_public_key_bytes(), addr)
                            print(f"[CRYPTO] Handshake completed with {addr_str}")
                        return
                    return
            
            # 3. ПЛАГИНЫ ПОЛУЧАЮТ РАСШИФРОВАННЫЕ ДАННЫЕ
            self.trigger("on_decrypted_packet", addr_str, msg)
            
            name = msg.get("n", "Guest")[:15]
            
            # Первое подключение
            if addr_str not in self.players:
                self.players[addr_str] = {
                    "n": name, "hp": 100, "x": 0, "y": 2, "z": 0, "r": 0,
                    "color": random.choice(PLAYER_COLORS)
                }
                self.clients[addr_str] = addr
                self.player_inventory[addr_str] = {"stone": 10, "brick": 10, "wood": 10}
                self.build_mode[addr_str] = "survival"
                self.say(f"{name} joined!")
                self.trigger("on_join", name, addr_str)
                join_data = orjson.dumps({"map": self.map_blocks, "inventory": self.player_inventory[addr_str]})
                encrypted_join = self.crypto.encrypt_packet(addr_str, join_data)
                self.transport.sendto(encrypted_join, addr)
            
            self.last_seen[addr_str] = time.time()
            
            # Обновление позиции
            if "x" in msg and self.players[addr_str]['hp'] > 0:
                self.players[addr_str].update({"x": msg["x"], "y": msg["y"], "z": msg["z"], "r": msg["r"]})
            
            # Чат и команды
            if "chat" in msg:
                chat_msg = f"{name}: {msg['chat'][:50]}"
                self.chat.append(chat_msg)
                if len(self.chat) > 8:
                    self.chat.pop(0)
                self.trigger("on_chat", name, msg['chat'])
                
                cmd = msg['chat']
                if cmd.startswith('/creative'):
                    self.build_mode[addr_str] = "creative"
                    self.say(f"{name} переключился в креатив")
                elif cmd.startswith('/survival'):
                    self.build_mode[addr_str] = "survival"
                    self.say(f"{name} переключился в выживание")
                elif cmd.startswith('/give'):
                    try:
                        _, block_type, amount = cmd.split()
                        amount = int(amount)
                        if addr_str in self.player_inventory and block_type in self.player_inventory[addr_str]:
                            self.player_inventory[addr_str][block_type] += amount
                            self.say(f"{name} получил {amount} {BLOCK_TYPES[block_type]['name']}!")
                    except:
                        self.say("Usage: /give <тип> <количество>")
                elif cmd.startswith('/build'):
                    try:
                        parts = cmd.split()
                        if len(parts) >= 5:
                            _, block_type, x, y, z = parts[:5]
                            pos = [float(x), float(y), float(z)]
                            if block_type not in BLOCK_TYPES:
                                self.say(f"Нет блока {block_type}")
                            elif self.place_block(addr_str, block_type, pos):
                                self.say(f"{name} построил {BLOCK_TYPES[block_type]['name']}!")
                            else:
                                self.say("Не могу построить тут!")
                    except Exception as e:
                        self.say(f"Ошибка: {e}")
                elif cmd.startswith('/break'):
                    try:
                        _, x, y, z = cmd.split()
                        pos = [float(x), float(y), float(z)]
                        if self.break_block(addr_str, pos):
                            self.say(f"{name} сломал блок!")
                    except:
                        self.say("Usage: /break <x> <y> <z>")
                elif cmd.startswith('/inv'):
                    if addr_str in self.player_inventory:
                        inv_str = ", ".join([f"{BLOCK_TYPES[k]['name']}: {v}" for k, v in self.player_inventory[addr_str].items()])
                        self.say(f"Инвентарь: {inv_str}")
                elif cmd.startswith('/tnt') and self.build_mode.get(addr_str) == "creative":
                    try:
                        _, x, y, z = cmd.split()
                        self.spawn_tnt(float(x), float(y), float(z))
                    except:
                        self.spawn_tnt(self.players[addr_str]["x"], self.players[addr_str]["y"] + 2, self.players[addr_str]["z"])
            
            # Хиты и выстрелы
            if msg.get("hit"):
                target = msg["hit"]
                for p_addr, p_data in self.players.items():
                    if p_data["n"] == target and p_data["hp"] > 0:
                        p_data["hp"] -= 20
                        if p_data["hp"] <= 0:
                            self.say(f"{name} killed {target}")
                            self.trigger("on_death", target, name)
            if msg.get("shot"):
                self.pending_shots.append(msg["shot"])
            if msg.get("respawn"):
                self.players[addr_str].update({"hp": 100, "x": 0, "y": 2, "z": 0})
            if "inventory_update" in msg and addr_str in self.player_inventory:
                for k, v in msg["inventory_update"].items():
                    if k in self.player_inventory[addr_str]:
                        self.player_inventory[addr_str][k] = v
                        
        except Exception as e:
            print(f"[CoreMaster] Error: {e}")

async def watch_console(server):
    loop = asyncio.get_event_loop()
    while True:
        cmd = await loop.run_in_executor(None, input, "CMD: ")
        if cmd == '/stop':
            server.trigger("on_stop")
            print("[CoreMaster] Stopping...")
            await asyncio.sleep(3)
            os._exit(0)
        elif cmd.startswith('/tnt'):
            try:
                _, x, y, z = cmd.split()
                server.spawn_tnt(float(x), float(y), float(z))
            except:
                print("Usage: /tnt x y z")
        elif cmd.startswith('/give'):
            try:
                _, player, block_type, amount = cmd.split()
                for addr, p_data in server.players.items():
                    if p_data["n"] == player and addr in server.player_inventory:
                        server.player_inventory[addr][block_type] += int(amount)
                        print(f"Gave {player} {amount} {block_type}")
                        break
            except:
                print("Usage: /give <player> <block_type> <amount>")

async def main():
    print('[CoreMaster] CoreMaster v2.0 - Encrypted UDP Game Server')
    print('[CoreMaster] Commands: /stop, /tnt x y z, /give player block amount')
    print('[CRYPTO] AES-256-GCM with unique keys per client')
    print('[PLUGINS] Plugins receive RAW and DECRYPTED packet events')
    loop = asyncio.get_running_loop()
    transport, server = await loop.create_datagram_endpoint(GameServer, local_addr=('0.0.0.0', 9999))
    await watch_console(server)

if __name__ == "__main__":
    asyncio.run(main())