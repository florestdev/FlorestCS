from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
import socket, orjson, time, math, random
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes

# --- КРИПТОГРАФИЯ КЛИЕНТА ---
class ClientCrypto:
    def __init__(self):
        self.private_key = x25519.X25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.server_public_key = None
        self.session_key = None
        self.send_nonce = 0
        self.recv_nonce = 0
        self.handshake_complete = False
    
    def get_public_key_bytes(self):
        return self.public_key.public_bytes_raw()
    
    def process_server_public_key(self, server_public_bytes):
        try:
            self.server_public_key = x25519.X25519PublicKey.from_public_bytes(server_public_bytes)
            shared_secret = self.private_key.exchange(self.server_public_key)
            
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=b'coremaster-game-encryption'
            )
            self.session_key = hkdf.derive(shared_secret)
            self.handshake_complete = True
            print("✅ Криптографический канал установлен (уникальный ключ)")
            return True
        except Exception as e:
            print(f"⚠️ Ошибка handshake: {e}")
            return False
    
    def encrypt_packet(self, data: bytes) -> bytes:
        if not self.handshake_complete:
            return data
        try:
            aesgcm = AESGCM(self.session_key)
            nonce = self.send_nonce.to_bytes(12, 'big')
            encrypted = aesgcm.encrypt(nonce, data, None)
            self.send_nonce += 1
            return encrypted
        except Exception as e:
            print(f"⚠️ Ошибка шифрования: {e}")
            return data
    
    def decrypt_packet(self, encrypted_data: bytes) -> bytes:
        if not self.handshake_complete:
            return encrypted_data
        
        for offset in range(4):
            try:
                aesgcm = AESGCM(self.session_key)
                nonce = (self.recv_nonce + offset).to_bytes(12, 'big')
                decrypted = aesgcm.decrypt(nonce, encrypted_data, None)
                self.recv_nonce += offset + 1
                return decrypted
            except:
                continue
        
        print(f"⚠️ Ошибка дешифрования")
        return None

# --- ИНИЦИАЛИЗАЦИЯ DISCORD RICH PRESENCE ---
presence = None
discord_available = False
presence_enabled = True  # ВКЛЮЧЕН ПО УМОЛЧАНИЮ
presence_level = 2
last_presence_update = 0
presence_update_interval = 15  # Обновлять каждые 15 секунд

try:
    from pypresence.presence import Presence
    import pypresence.exceptions
    
    try:
        presence = Presence("1562145701205643276")
        presence.connect()
        discord_available = True
        print("✅ Discord Rich Presence подключен")
    except pypresence.exceptions.DiscordNotFound:
        print("⚠️ Discord не запущен или не установлен. Rich Presence отключен.")
    except Exception as e:
        print(f"⚠️ Ошибка подключения Discord: {e}")
        
except ImportError:
    print("⚠️ pypresence не установлен. Установите: pip install pypresence")
except Exception as e:
    print(f"⚠️ Неизвестная ошибка Discord: {e}")

def setup_discord_events():
    global presence, discord_available
    if not discord_available or not presence:
        return
    try:
        presence.register_event('ACTIVITY_JOIN')
        presence.register_event('ACTIVITY_JOIN_REQUEST')
        presence.register_event('ACTIVITY_SPECTATE')
        print("✅ Discord события зарегистрированы")
    except Exception as e:
        print(f"⚠️ Ошибка регистрации событий Discord: {e}")

def handle_discord_events():
    global presence, discord_available, SERVER, menu, input_ip, input_n, my_name
    if not discord_available or not presence:
        return
    try:
        events = presence.get_events()
        for event in events:
            if event['type'] == 'ACTIVITY_JOIN':
                join_data = event.get('data', {})
                join_secret = join_data.get('join_secret', '')
                if join_secret and ':' in join_secret:
                    ip, port = join_secret.split(':')
                    print(f"🎮 Приглашение присоединиться к серверу {ip}:{port}")
                    if menu.enabled:
                        input_ip.text = f"{ip}:{port}"
                        start()
            elif event['type'] == 'ACTIVITY_JOIN_REQUEST':
                user = event.get('data', {}).get('user', {})
                username = user.get('username', 'Unknown')
                print(f"📨 {username} хочет присоединиться к игре!")
    except Exception as e:
        pass

def generate_join_secret():
    global SERVER
    return f"{SERVER[0]}:{SERVER[1]}"

def update_presence(force=False):
    global presence_enabled, discord_available, presence, my_name, SERVER, enemies, last_presence_update, presence_update_interval
    
    # Принудительное обновление или проверка интервала
    now = time.time()
    if not force and (now - last_presence_update) < presence_update_interval:
        return
    
    if not discord_available or not presence:
        return
    
    # ВСЕГДА обновляем, если presence_enabled == True
    if presence_enabled:
        try:
            players_online = len(enemies) + 1
            if presence_level == 1:
                presence.update(
                    details="Играет в CoreMaster",
                    state=f"На сервере: {SERVER[0]}:{SERVER[1]}",
                    start=time.time()
                )
            else:  # level 2 по умолчанию
                presence.update(
                    details=f'🎮 Многопользовательский режим | 👥 {players_online} игроков',
                    state=f'🔧 Сервер: {SERVER[0]}:{SERVER[1]} | Режим: {build_mode if "build_mode" in globals() else "survival"}',
                    start=time.time(),
                    join=generate_join_secret(),
                    party_id=f"party_{SERVER[0]}_{SERVER[1]}",
                    party_size=[players_online, 32]
                )
            last_presence_update = now
            print(f"✅ Discord Presence обновлен: {players_online} игроков онлайн")
        except Exception as e:
            print(f"⚠️ Ошибка обновления Discord статуса: {e}")
    else:
        # Presence отключен сервером - очищаем
        clear_presence()

def clear_presence():
    global presence, discord_available
    if discord_available and presence:
        try:
            presence.clear()
            print("🎮 Discord Presence очищен")
        except:
            pass

# Инициализация событий Discord
if discord_available and presence:
    setup_discord_events()
    # НЕМЕДЛЕННОЕ обновление при старте
    update_presence(force=True)

# --- ОСНОВНОЙ КОД ИГРЫ ---
app = Ursina(show_ursina_splash=False)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False)
SERVER = ("127.0.0.1", 9999)

crypto = ClientCrypto()
handshake_sent = False
handshake_start_time = 0
game_started = False

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='ursina')
import logging
logging.getLogger("ursina.text").setLevel(logging.ERROR)

Entity(model='plane', scale=200, texture='grass', collider='box')
Sky()

player = FirstPersonController(y=2, enabled=False)
enemies = {}
my_name, my_hp = "", 100
map_loaded = False
last_server_update = time.time()
is_dead = False

build_mode = "survival"
inventory = {"stone": 10, "brick": 10, "wood": 10}
current_block_type = "stone"
highlighted_block = None
show_inventory = False
build_distance = 5.0

def set_current_block(block_type):
    global current_block_type
    current_block_type = block_type
    print(f"Текущий блок: {block_type}")
    for btn in block_buttons:
        btn.color = color.gray
        if btn.block_type == block_type:
            btn.color = color.green

tnt_entities = {}
explosion_particles = []
map_blocks = []
camera_shake_amount = 0

build_menu = Entity(parent=camera.ui, enabled=False)

block_buttons = []
block_types_list = ["stone", "brick", "wood"]
for i, block_type in enumerate(block_types_list):
    btn = Button(
        parent=build_menu,
        model='quad',
        color=color.gray,
        scale=(0.1, 0.1),
        position=(-0.4 + i*0.15, -0.4),
        text=block_type[:3],
        tooltip=Tooltip(block_type)
    )
    btn.block_type = block_type
    btn.on_click = Func(set_current_block, block_type)
    block_buttons.append(btn)

inventory_text = Text(
    parent=camera.ui,
    text='',
    position=(-0.7, 0.4),
    scale=1.5,
    color=color.white,
    enabled=False
)

mode_text = Text(
    parent=camera.ui,
    text='Режим: Выживание',
    position=(0.7, 0.4),
    scale=1.5,
    color=color.green,
    enabled=False
)

build_crosshair = Entity(
    parent=camera.ui,
    model='quad',
    color=color.white,
    scale=0.03,
    enabled=False
)

class Bullet(Entity):
    def __init__(self, pos, direction):
        super().__init__(model='sphere', color=color.yellow, scale=0.15, position=pos, collider='sphere')
        self.direction = Vec3(*direction)
        destroy(self, delay=1.0)
    def update(self):
        self.position += self.direction * 100 * time.dt
        if self.intersects().hit: destroy(self)

class TNT(Entity):
    def __init__(self, tnt_id, position, fuse_time=3.0):
        super().__init__(
            model='cube',
            color=color.red,
            scale=0.8,
            position=position,
            collider='box'
        )
        self.tnt_id = tnt_id
        self.fuse_time = fuse_time
        self.spawn_time = time.time()
        self.active = True
        
        self.fuse_particles = []
        for i in range(4):
            particle = Entity(
                parent=self,
                model='cube',
                color=color.yellow,
                scale=0.1,
                position=(0, 0.5, 0)
            )
            self.fuse_particles.append(particle)
        
        self.timer_text = Text(
            text=str(int(fuse_time)),
            parent=self,
            y=1.5,
            scale=5,
            color=color.white,
            billboarding=True
        )

class Explosion(Entity):
    def __init__(self, position, radius=5.0):
        super().__init__(position=position)
        self.radius = radius
        self.particles = []
        self.start_time = time.time()
        
        for _ in range(20):
            particle = Entity(
                model='sphere',
                color=color.orange,
                scale=0.2,
                position=position
            )
            particle.velocity = Vec3(
                random.uniform(-1, 1),
                random.uniform(0.5, 2),
                random.uniform(-1, 1)
            ) * 10
            self.particles.append(particle)
        
        self.flash = Entity(
            model='sphere',
            color=color.yellow,
            scale=0.1,
            position=position
        )
        
        global camera_shake_amount
        if distance(player.position, position) < radius * 2:
            camera_shake_amount = 0.5
        
        print("💥 BOOM!")
        
    def update(self):
        now = time.time()
        age = now - self.start_time
        
        if age > 1.0:
            for p in self.particles:
                destroy(p)
            destroy(self.flash)
            destroy(self)
            return
        
        for p in self.particles:
            p.position += p.velocity * time.dt
            p.velocity *= 0.95
            p.scale *= 0.98
            p.color = color.color(0, 1, 1, max(0, 1 - age))
            
        self.flash.scale = age * 20
        self.flash.color = color.color(0, 1, 1, max(0, 1 - age * 2))

class DestructibleBlock(Entity):
    def __init__(self, block_data):
        block_type = block_data.get('type', 'stone')
        colors = {
            'stone': color.gray,
            'brick': color.red,
            'wood': color.brown,
            'bedrock': color.black
        }
        
        super().__init__(
            model='cube',
            collider='box',
            position=Vec3(*block_data['pos']),
            scale=Vec3(*block_data.get('scale', [1, 1, 1])),
            color=colors.get(block_type, color.gray),
            texture='white_cube'
        )
        self.block_id = block_data.get('id', 'unknown')
        self.block_type = block_type
        self.destructible = block_data.get('destructible', True)
        self.original_color = self.color
        self.hp = block_data.get('hp', 100)
        self.max_hp = block_data.get('hp', 100)
        
    def update(self):
        if hasattr(self, 'hp') and self.hp < self.max_hp:
            health_ratio = self.hp / self.max_hp
            self.color = color.color(
                self.original_color.hue(),
                self.original_color.saturation(),
                self.original_color.value() * health_ratio
            )
        
    def destroy_block(self):
        if not self.destructible:
            return
            
        for _ in range(10):
            particle = Entity(
                model='cube',
                color=self.original_color,
                scale=0.2,
                position=self.position + Vec3(
                    random.uniform(-0.5, 0.5),
                    random.uniform(-0.5, 0.5),
                    random.uniform(-0.5, 0.5)
                )
            )
            particle.velocity = Vec3(
                random.uniform(-5, 5),
                random.uniform(2, 8),
                random.uniform(-5, 5)
            )
            particle.angular_velocity = Vec3(
                random.uniform(-10, 10),
                random.uniform(-10, 10),
                random.uniform(-10, 10)
            )
            
            def update_particle(particle):
                particle.position += particle.velocity * time.dt
                particle.velocity *= 0.95
                particle.rotation += particle.angular_velocity * time.dt
                particle.scale *= 0.99
                
            particle.update = Func(update_particle, particle)
            destroy(particle, delay=2.0)
        
        destroy(self)

gun = Entity(parent=camera, position=(0.6, -0.4, 1), model='cube', scale=(0.1, 0.1, 1.2), color=color.black, enabled=False)

chat_bg = Entity(parent=camera.ui, model='quad', color=color.black66, scale=(0.5, 0.25), x=-0.63, y=0.35)
chat_display = Text(text='', parent=camera.ui, scale=1.1, x=-0.86, y=0.45)
chat_input = InputField(y=-0.45, scale=(0.5, 0.04), enabled=False)

def create_enemy(name, p_color):
    e = Entity(model=None, collider='box', scale=(1, 2, 1), origin_y=-0.5)
    clr = getattr(color, p_color)
    e.head = Entity(parent=e, model='cube', color=color.peach, scale=(0.3, 0.3, 0.3), y=1.2)
    e.body = Entity(parent=e, model='cube', color=clr, scale=(0.6, 0.8, 0.3), y=0.6)
    e.l_arm = Entity(parent=e, model='cube', color=color.white, scale=(0.15, 0.7, 0.15), x=-0.4, y=0.6)
    e.r_arm = Entity(parent=e, model='cube', color=color.white, scale=(0.15, 0.7, 0.15), x=0.4, y=0.6)
    e.l_leg = Entity(parent=e, model='cube', color=color.black, scale=(0.2, 0.6, 0.2), x=-0.15, y=0.0)
    e.r_leg = Entity(parent=e, model='cube', color=color.black, scale=(0.2, 0.6, 0.2), x=0.15, y=0.0)
    e.label = Text(text=name, parent=e, y=1.8, scale=8, color=color.yellow, billboarding=True, origin=(0,0))
    e.hp_bar = Entity(parent=e, model='quad', color=color.green, scale=(1, 0.1), y=1.6, billboarding=True)
    e.old_hp, e.base_color = 100, clr
    return e

def get_target_block_position():
    hit_info = raycast(
        camera.world_position + camera.forward * 2, 
        camera.forward, 
        distance=build_distance,
        ignore=[player]
    )
    
    if hit_info.hit:
        normal = hit_info.normal
        block_pos = hit_info.entity.position
        new_pos = Vec3(
            block_pos.x + normal.x,
            block_pos.y + normal.y,
            block_pos.z + normal.z
        )
        return new_pos, hit_info.entity
    
    hit_ground = raycast(
        camera.world_position,
        camera.forward,
        distance=build_distance,
        ignore=[player]
    )
    
    if hit_ground.hit:
        return hit_ground.entity.position + Vec3(0, 1, 0), hit_ground.entity
    
    return None, None

def get_break_block():
    hit_info = raycast(
        camera.world_position, 
        camera.forward, 
        distance=build_distance,
        ignore=[player]
    )
    
    if hit_info.hit and hasattr(hit_info.entity, 'block_type'):
        return hit_info.entity
    return None

def build_block():
    pos, target = get_target_block_position()
    
    if pos:
        for block in map_blocks:
            if distance(block.position, pos) < 0.5:
                print("Тут уже есть блок!")
                return
        
        if build_mode == "survival":
            if inventory.get(current_block_type, 0) <= 0:
                print(f"Нет {current_block_type} в инвентаре!")
                return
        
        cmd = f"/build {current_block_type} {pos.x:.1f} {pos.y:.1f} {pos.z:.1f}"
        data = orjson.dumps({"n": my_name, "chat": cmd})
        encrypted = crypto.encrypt_packet(data)
        sock.sendto(encrypted, SERVER)
        
        particle = Entity(
            model='cube',
            color=color.white,
            scale=0.3,
            position=pos
        )
        destroy(particle, delay=0.2)

def break_block():
    global inventory
    
    block = get_break_block()
    
    if block and block.destructible:
        pos = block.position
        cmd = f"/break {pos.x:.1f} {pos.y:.1f} {pos.z:.1f}"
        data = orjson.dumps({"n": my_name, "chat": cmd})
        encrypted = crypto.encrypt_packet(data)
        sock.sendto(encrypted, SERVER)
        
        block.destroy_block()
        if block in map_blocks:
            map_blocks.remove(block)

def toggle_build_menu():
    global show_inventory, highlighted_block
    
    show_inventory = not show_inventory
    build_menu.enabled = show_inventory
    inventory_text.enabled = show_inventory
    mode_text.enabled = show_inventory
    build_crosshair.enabled = show_inventory
    
    if show_inventory:
        mouse.locked = False
        mouse.visible = True
        update_inventory_display()
    else:
        mouse.locked = True
        mouse.visible = False
        if highlighted_block:
            highlighted_block.color = highlighted_block.original_color
            highlighted_block = None

def update_inventory_display():
    if show_inventory:
        inv_str = f"Инвентарь:\n"
        for block_type, count in inventory.items():
            inv_str += f"• {block_type}: {count}\n"
        inv_str += f"\nРежим: {build_mode}\nТип: {current_block_type}"
        inventory_text.text = inv_str
        
        mode_text.text = f"Режим: {'Креатив' if build_mode == 'creative' else 'Выживание'}"

def set_build_mode(mode):
    global build_mode
    build_mode = mode
    cmd = f"/{mode}"
    data = orjson.dumps({"n": my_name, "chat": cmd})
    encrypted = crypto.encrypt_packet(data)
    sock.sendto(encrypted, SERVER)
    update_inventory_display()

menu = Entity(parent=camera.ui)
input_n = InputField(parent=menu, y=0.1, placeholder='Name...')
input_ip = InputField(parent=menu, y=0.0, placeholder='127.0.0.1 или domain.ru')
error_text = Text(parent=menu, y=-0.1, text='', color=color.red, scale=2)

def validate_server_address(address):
    address = address.strip()
    if not address:
        return None, None, "Введите адрес сервера!"
    
    host = address
    port = 9999
    
    if ':' in address:
        parts = address.split(':')
        if len(parts) != 2:
            return None, None, "Неправильный формат! Используй: адрес:порт"
        
        host = parts[0]
        try:
            port = int(parts[1])
            if port < 1 or port > 65535:
                return None, None, "Порт должен быть от 1 до 65535!"
        except ValueError:
            return None, None, "Порт должен быть числом!"
    
    import re
    ip_pattern = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
    ip_match = re.match(ip_pattern, host)
    
    if ip_match:
        for octet in ip_match.groups():
            if int(octet) > 255:
                return None, None, "IP-адрес невалидный! Числа должны быть ≤ 255"
        return host, port, None
    
    if len(host) > 253:
        return None, None, "Домен слишком длинный!"
    
    domain_pattern = r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]*[a-zA-Z0-9]$'
    if not re.match(domain_pattern, host):
        return None, None, "В домене только буквы, цифры и дефисы!"
    
    if '..' in host:
        return None, None, "В домене не может быть двух точек подряд!"
    
    if host.startswith('.') or host.endswith('.'):
        return None, None, "Домен не может начинаться или заканчиваться точкой!"
    
    if '.' not in host:
        return None, None, "Домен должен содержать точку (например: coremaster.ru)"
    
    return host, port, None

def perform_handshake():
    global handshake_sent, handshake_start_time
    try:
        sock.sendto(crypto.get_public_key_bytes(), SERVER)
        handshake_sent = True
        handshake_start_time = time.time()
        print("🔐 Отправлен публичный ключ серверу...")
    except Exception as e:
        print(f"⚠️ Ошибка handshake: {e}")

def start_game():
    global game_started, my_name, SERVER, presence_enabled
    
    menu.enabled = False
    player.enabled = True
    gun.enabled = True
    mouse.locked = True
    build_menu.enabled = False
    inventory_text.enabled = False
    mode_text.enabled = False
    build_crosshair.enabled = False
    error_text.text = ""
    
    # Presence уже включен, просто обновляем с данными сервера
    if discord_available and presence:
        try:
            update_presence(force=True)
            print(f"✅ Discord статус обновлен: {SERVER[0]}:{SERVER[1]}")
        except Exception as e:
            print(f"⚠️ Ошибка обновления Discord статуса: {e}")
    
    # Отправляем имя игрока
    name_packet = orjson.dumps({"n": my_name})
    encrypted_name = crypto.encrypt_packet(name_packet)
    sock.sendto(encrypted_name, SERVER)
    print(f"🔐 Защищенное соединение установлено! Имя: {my_name}")
    game_started = True

def start():
    global my_name, SERVER, handshake_sent, game_started
    
    if not input_n.text:
        error_text.text = "Введите имя!"
        return
    
    host, port, error = validate_server_address(input_ip.text)
    if error:
        error_text.text = error
        return
    
    import socket
    try:
        try:
            socket.inet_aton(host)
            ip = host
        except socket.error:
            ip = socket.gethostbyname(host)
            print(f"Домен {host} резолвится в {ip}")
    except socket.gaierror:
        error_text.text = f"Не могу найти домен {host}!"
        return
    except Exception as e:
        error_text.text = f"Ошибка сети: {e}"
        return
    
    my_name = input_n.text
    SERVER = (ip, port)
    
    error_text.text = "Выполняется защищенное подключение..."
    print(f"🔐 Устанавливается защищенное соединение с {host}:{port}")
    
    perform_handshake()

start_btn = Button(parent=menu, text='START', scale=(0.2, 0.05), y=-0.1, on_click=start)

def input(key):
    if key == 'enter':
        if not chat_input.enabled and player.enabled:
            chat_input.enabled, chat_input.active, mouse.locked = True, True, False
        elif chat_input.enabled:
            if chat_input.text.strip():
                data = orjson.dumps({"n": my_name, "chat": chat_input.text})
                encrypted = crypto.encrypt_packet(data)
                sock.sendto(encrypted, SERVER)
            chat_input.text, chat_input.enabled, mouse.locked = "", False, True
    
    if player.enabled and not chat_input.enabled:
        if key == 'b':
            toggle_build_menu()
        
        if key == 'left mouse' and show_inventory:
            build_block()
        
        if key == 'right mouse' and show_inventory:
            break_block()
        
        if key == '1':
            set_current_block('stone')
        if key == '2':
            set_current_block('brick')
        if key == '3':
            set_current_block('wood')
        
        if key == 'c':
            set_build_mode('creative')
        if key == 's':
            set_build_mode('survival')
        
        if key == 'i':
            update_inventory_display()
            print(f"Инвентарь: {inventory}")

def update():
    global my_hp, last_server_update, map_loaded, map_blocks, camera_shake_amount, is_dead, inventory, build_mode, highlighted_block, presence_enabled, handshake_sent, handshake_start_time, game_started
    
    handle_discord_events()
    
    # Регулярное обновление Presence (каждые 15 секунд)
    if game_started and discord_available and presence:
        update_presence()
    
    if handshake_sent and not crypto.handshake_complete and not game_started:
        if time.time() - handshake_start_time > 5:
            print("⚠️ Таймаут handshake! Проверьте подключение к серверу")
            handshake_sent = False
            menu.enabled = True
            error_text.text = "Ошибка подключения: сервер не ответил"
    
    if camera_shake_amount > 0:
        camera_shake_amount -= time.dt
        offset = Vec3(
            random.uniform(-0.2, 0.2),
            random.uniform(-0.1, 0.1),
            0
        ) * camera_shake_amount * 2
        player.camera_pivot.position = offset
    else:
        player.camera_pivot.position = Vec3(0, 0, 0)
    
    if not player.enabled and not menu.enabled and not game_started:
        return

    shot_data, hit_name = None, None
    respawn_signal = False
    
    if player.enabled and show_inventory and not chat_input.enabled:
        block_to_break = get_break_block()
        if block_to_break != highlighted_block:
            if highlighted_block:
                highlighted_block.color = highlighted_block.original_color
            highlighted_block = block_to_break
            if highlighted_block:
                highlighted_block.color = color.white
    elif not player.enabled:
        pass
    else:
        if highlighted_block:
            highlighted_block.color = highlighted_block.original_color
            highlighted_block = None
    
    if my_hp <= 0 and player.enabled:
        if not is_dead:
            is_dead = True
            respawn_signal = True
            print("💀 УМЕР - МГНОВЕННЫЙ РЕСПАВН!")
            
            death_effect = Entity(
                parent=camera.ui,
                model='quad',
                color=color.rgba(1, 0, 0, 0.5),
                scale=2
            )
            destroy(death_effect, delay=0.2)
        
        player.enabled = False
        gun.enabled = False
        player.position = Vec3(0, -50, 0)
    elif player.enabled:
        if is_dead:
            is_dead = False
            player.enabled = True
            gun.enabled = True
            mouse.locked = True
            player.position = Vec3(0, 2, 0)
            
        if mouse.left and not chat_input.enabled and not show_inventory:
            Bullet(gun.world_position, camera.forward)
            shot_data = {"pos": list(gun.world_position), "dir": list(camera.forward)}
            ray = raycast(camera.world_position, camera.forward, distance=50)
            if ray.hit:
                for name, en in enemies.items():
                    if ray.entity == en or ray.entity in en.children: 
                        hit_name = name
                
                for tnt_id, tnt in list(tnt_entities.items()):
                    if ray.entity == tnt:
                        Explosion(tnt.position)
                        destroy(tnt)
                        del tnt_entities[tnt_id]
                        break

    # Отправка и получение данных
    try:
        if crypto.handshake_complete and not game_started:
            start_game()
        
        if crypto.handshake_complete and player.enabled:
            packet = {
                "n": my_name, 
                "x": player.x if not is_dead else 0, 
                "y": player.y if not is_dead else -50, 
                "z": player.z if not is_dead else 0, 
                "r": player.rotation_y if not is_dead else 0, 
                "hit": hit_name, 
                "shot": shot_data, 
                "respawn": respawn_signal
            }
            data = orjson.dumps(packet)
            encrypted = crypto.encrypt_packet(data)
            sock.sendto(encrypted, SERVER)
        
        while True:
            raw, _ = sock.recvfrom(10240)
            
            if crypto.handshake_complete:
                decrypted = crypto.decrypt_packet(raw)
                if decrypted is None:
                    continue
                data = orjson.loads(decrypted)
            else:
                if len(raw) == 32 and not crypto.handshake_complete:
                    if crypto.process_server_public_key(raw):
                        print("🔐 Handshake успешен!")
                        # После успешного handshake обновляем Presence
                        if discord_available and presence:
                            update_presence(force=True)
                    continue
                else:
                    continue
            
            last_server_update = time.time()
            
            # --- ОБРАБОТКА КОМАНДЫ PRESENCE ОТ СЕРВЕРА ---
            if "cmd" in data and data["cmd"] == "presence":
                if data.get("state") == "off":
                    presence_enabled = False
                    clear_presence()
                    print("🎮 Discord Presence отключен сервером")
                elif data.get("state") == "on":
                    presence_enabled = True
                    update_presence(force=True)
                    print("🎮 Discord Presence включен сервером")
            
            if "map" in data:
                if not map_loaded:
                    for obj in data["map"]:
                        block = DestructibleBlock(obj)
                        map_blocks.append(block)
                    map_loaded = True
                else:
                    new_block_ids = [b.get('id') for b in data["map"] if b.get('id')]
                    for block in map_blocks[:]:
                        if hasattr(block, 'block_id') and block.block_id not in new_block_ids:
                            map_blocks.remove(block)
                            destroy(block)
                    
                    existing_ids = [b.block_id for b in map_blocks if hasattr(b, 'block_id')]
                    for obj in data["map"]:
                        if obj.get('id') not in existing_ids:
                            block = DestructibleBlock(obj)
                            map_blocks.append(block)
            
            if "chat" in data:
                chat_display.text = "\n".join(data["chat"])
                
                for msg in data["chat"]:
                    if "переключился в режим креатива" in msg and my_name in msg:
                        build_mode = "creative"
                        update_inventory_display()
                    if "переключился в режим выживания" in msg and my_name in msg:
                        build_mode = "survival"
                        update_inventory_display()
                    if "получил" in msg and my_name in msg and "Камень" in msg:
                        inventory["stone"] += 1
                        update_inventory_display()
                    if "получил" in msg and my_name in msg and "Кирпич" in msg:
                        inventory["brick"] += 1
                        update_inventory_display()
                    if "получил" in msg and my_name in msg and "Дерево" in msg:
                        inventory["wood"] += 1
                        update_inventory_display()
            
            if "inventory" in data:
                inventory = data["inventory"]
                update_inventory_display()
            
            if "shots" in data:
                for s in data["shots"]:
                    if s: 
                        Bullet(Vec3(*s["pos"]), Vec3(*s["dir"]))
            
            if "tnt_spawn" in data:
                tnt_data = data["tnt_spawn"]
                if tnt_data["id"] not in tnt_entities:
                    tnt = TNT(
                        tnt_data["id"],
                        Vec3(*tnt_data["pos"]),
                        tnt_data["fuse"]
                    )
                    tnt_entities[tnt_data["id"]] = tnt                    
                    print(f"💣 TNT spawned at {tnt_data['pos']}")
            
            if "tnt_active" in data:
                active_ids = [t["id"] for t in data["tnt_active"]]
                for tnt_id in list(tnt_entities.keys()):
                    if tnt_id not in active_ids:
                        if tnt_entities[tnt_id] in tnt_entities:
                            destroy(tnt_entities[tnt_id])
                            del tnt_entities[tnt_id]
            
            if "explosion" in data:
                exp = data["explosion"]
                Explosion(Vec3(*exp["pos"]), exp["radius"])
                
                destroyed = exp.get("destroyed_blocks", [])
                for block in map_blocks[:]:
                    if hasattr(block, 'block_id') and block.block_id in destroyed:
                        block.destroy_block()
                        map_blocks.remove(block)
                
                if exp.get("players_hit"):
                    for hit in exp["players_hit"]:
                        if hit["name"] == my_name:
                            print(f"💥 You took {hit['damage']} damage!")
                            hurt_effect = Entity(
                                parent=camera.ui,
                                model='quad',
                                color=color.rgba(1, 0, 0, 0.3),
                                scale=2
                            )
                            destroy(hurt_effect, delay=0.2)
            
            if "players" in data:
                current = [p["n"] for p in data["players"] if p["n"] != my_name]
                for n in list(enemies.keys()):
                    if n not in current: 
                        destroy(enemies[n])
                        del enemies[n]
                
                for p in data["players"]:
                    if p["n"] == my_name:
                        old_hp = my_hp
                        my_hp = p["hp"]
                        
                        if my_hp < old_hp:
                            hurt_effect = Entity(
                                parent=camera.ui,
                                model='quad',
                                color=color.rgba(1, 0, 0, 0.3),
                                scale=2
                            )
                            destroy(hurt_effect, delay=0.2)
                        continue
                    
                    if p["n"] not in enemies: 
                        enemies[p["n"]] = create_enemy(p["n"], p.get("color", "red"))
                        # При появлении нового игрока обновляем Presence
                        if game_started:
                            update_presence(force=True)
                    
                    en = enemies[p["n"]]
                    en.enabled = p["hp"] > 0
                    if en.enabled:
                        en.position = lerp(en.position, Vec3(p['x'], p['y'], p['z']), time.dt * 25)
                        en.rotation_y = p['r']
                        if p['hp'] < en.old_hp:
                            en.body.color = color.white
                            invoke(setattr, en.body, 'color', en.base_color, delay=0.1)
                        en.old_hp, en.hp_bar.scale_x = p['hp'], p['hp'] / 100
                    
    except socket.error:
        pass
    except Exception as e:
        print(f"Error: {e}")
    
    if time.time() - last_server_update > 5 and game_started: 
        chat_display.text = "LOST CONNECTION"

def main():
    app.run()