# FlorestCS - proxy. Not a gaming server!
import asyncio
import time

PROXY_HOST = '0.0.0.0'
PROXY_PORT = 9900
BACKEND_HOST = '127.0.0.1'
BACKEND_PORT = 9999

class UDPProxyProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.clients = {}  # addr -> время последнего пакета
        self.backend_addr = (BACKEND_HOST, BACKEND_PORT)
        self.transport = None
        self.packet_counter = 0
        self.pending_handshakes = {}  # временный маппинг для handshake
    
    def connection_made(self, transport):
        self.transport = transport
        print(f"🚀 Прокси запущен на {PROXY_HOST}:{PROXY_PORT}")
        print(f"📡 Ретрансляция на {BACKEND_HOST}:{BACKEND_PORT}")
        print("-" * 50)
    
    def datagram_received(self, data, addr):
        self.packet_counter += 1
        now = time.time()
        
        # Определяем, от кого пакет: от клиента или от бэкенда
        if addr == self.backend_addr:
            # Пакет от сервера (бэкенда)
            print(f"📨 [{self.packet_counter}] Ответ от сервера ({len(data)} байт)")
            
            # Пытаемся найти, кому предназначен этот ответ
            # По умолчанию рассылаем всем (старое поведение)
            sent_to = []
            
            # Если это handshake (32 байта) и есть ожидающий клиент
            if len(data) == 32 and self.pending_handshakes:
                # Отправляем клиенту, который инициировал handshake
                client_addr = list(self.pending_handshakes.keys())[0]
                self.transport.sendto(data, client_addr)
                sent_to.append(client_addr[1])
                # Очищаем после отправки
                self.pending_handshakes.clear()
            else:
                # Обычный пакет - рассылаем всем активным клиентам
                for client_addr in list(self.clients.keys()):
                    if now - self.clients[client_addr] < 30:
                        self.transport.sendto(data, client_addr)
                        sent_to.append(client_addr[1])
            
            if sent_to:
                print(f"   -> отправлено клиентам: {', '.join(map(str, sent_to[:3]))}{'...' if len(sent_to) > 3 else ''}")
            
            # Очищаем старых клиентов
            old_clients = [c for c, t in self.clients.items() if now - t > 30]
            for old in old_clients:
                if old in self.clients:
                    del self.clients[old]
                    print(f"🗑️ Клиент {old[1]} отключен по таймауту")
            
        else:
            # Пакет от клиента
            print(f"📨 [{self.packet_counter}] Запрос от клиента {addr[1]} ({len(data)} байт)")
            
            # Запоминаем клиента
            self.clients[addr] = now
            
            # Если это handshake (32 байта), запоминаем для обратного ответа
            if len(data) == 32:
                self.pending_handshakes[addr] = now
                print(f"   -> handshake от {addr[1]}, ожидаем ответ")
            
            # Отправляем на бэкенд
            self.transport.sendto(data, self.backend_addr)
            print(f"   -> переслано на сервер")
            
            # Очищаем старые handshake (старше 10 секунд)
            old_handshakes = [c for c, t in self.pending_handshakes.items() if now - t > 10]
            for old in old_handshakes:
                del self.pending_handshakes[old]
                print(f"🗑️ Handshake от {old[1]} истёк")
        
        # Статистика каждые 100 пакетов
        if self.packet_counter % 100 == 0:
            print(f"📊 Статистика: {len(self.clients)} клиентов, ожидание handshake: {len(self.pending_handshakes)}")
            print(f"   обработано пакетов: {self.packet_counter}")

async def main():
    loop = asyncio.get_running_loop()
    
    transport, protocol = await loop.create_datagram_endpoint(
        UDPProxyProtocol,
        local_addr=(PROXY_HOST, PROXY_PORT)
    )
    
    print("✅ Прокси готов к работе!")
    print(f"🔗 Подключайтесь к localhost:{PROXY_PORT} (или вашему IP)")
    print("🛑 Нажми Ctrl+C для остановки\n")
    
    try:
        await asyncio.Future()  # бесконечно работаем
    except KeyboardInterrupt:
        print("\n🛑 Остановка прокси...")
        transport.close()

if __name__ == "__main__":
    print("=" * 50)
    print("🔒 FlorestCS UDP Proxy (Fixed Handshake)")
    print("=" * 50)
    asyncio.run(main())