import time
import sys
import ctypes
import threading
import queue

# =========================
# IMPORTS COM PROTEÇÃO
# =========================
try:
    import cv2
except ImportError:
    print("Erro: OpenCV (cv2) não está instalado.")
    print("Instale com: py -m pip install opencv-python")
    sys.exit()

try:
    import numpy as np
except ImportError:
    print("Erro: numpy não está instalado.")
    print("Instale com: py -m pip install numpy")
    sys.exit()

try:
    from mss import mss
except ImportError:
    print("Erro: mss não está instalado.")
    print("Instale com: py -m pip install mss")
    sys.exit()

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Erro: pyserial não está instalado.")
    print("Instale com: py -m pip install pyserial")
    sys.exit()

# =========================
# PEGAR RESOLUÇÃO REAL
# =========================
def get_screen_resolution():
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080

# =========================
# DETECÇÃO AUTOMÁTICA DA PORTA SERIAL
# =========================
def find_arduino_port():
    ports    = list(serial.tools.list_ports.comports())
    keywords = ["arduino", "ch340", "cp210", "usb serial", "usbserial"]

    for port in ports:
        if any(kw in (port.description or "").lower() for kw in keywords):
            print(f"Arduino detectado: {port.device} — {port.description}")
            return port.device

    if not ports:
        print("Nenhuma porta serial encontrada. Verifique a conexão USB.")
        sys.exit()

    print("\nPortas seriais disponíveis:")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p.device} — {p.description}")

    while True:
        try:
            choice = int(input("\nDigite o número da porta do Arduino: "))
            if 0 <= choice < len(ports):
                return ports[choice].device
        except ValueError:
            pass
        print("Opção inválida.")

# =========================
# THREAD SERIAL — fila desacoplada do loop principal
# =========================
serial_queue  = queue.Queue(maxsize=2)   # máximo 2 comandos na fila
serial_thread_running = True

def serial_worker(port: str, baud: int = 115200):
    """
    Roda em thread separada.
    Lê pacotes da fila e envia ao Arduino sem bloquear o loop de visão.
    """
    global serial_thread_running
    try:
        ser = serial.Serial(port, baud, timeout=1, write_timeout=0.05)
        time.sleep(2)   # aguarda reset do Arduino
        print(f"[Serial] Conectada: {port} @ {baud} baud")
    except serial.SerialException as e:
        print(f"[Serial] Erro ao abrir {port}: {e}")
        serial_thread_running = False
        return

    while serial_thread_running:
        try:
            dx, dy = serial_queue.get(timeout=0.1)
            packet = bytes([
                dx & 0xFF, (dx >> 8) & 0xFF,
                dy & 0xFF, (dy >> 8) & 0xFF,
            ])
            ser.write(packet)
            ser.flush()
        except queue.Empty:
            continue
        except serial.SerialTimeoutException:
            pass   # write_timeout expirou — descarta e segue
        except serial.SerialException as e:
            print(f"[Serial] Erro de comunicação: {e}")
            break

    ser.close()
    print("[Serial] Porta fechada.")

def move_mouse(dx: int, dy: int):
    """
    Coloca o movimento na fila serial (não bloqueia).
    Se a fila estiver cheia, descarta o comando mais antigo.
    """
    dx, dy = int(round(dx)), int(round(dy))
    if dx == 0 and dy == 0:
        return
    if serial_queue.full():
        try:
            serial_queue.get_nowait()   # remove o comando mais antigo
        except queue.Empty:
            pass
    serial_queue.put_nowait((dx, dy))

# =========================
# CONFIGURAÇÕES
# =========================
PURPLE_LOWER      = np.array([125, 50, 50],   dtype=np.uint8)
PURPLE_UPPER      = np.array([170, 255, 255], dtype=np.uint8)
FOV_SIZE          = 300
SHOW_DEBUG_WINDOW = True
PRINT_DEBUG       = True
MAX_MOVE          = 30      # pixels máximos por frame

# =========================
# PID CONTROLLER
# =========================
class PID:
    def __init__(self, p, i, d):
        self.p = p; self.i = i; self.d = d
        self.last_err = 0.0; self.integral = 0.0

    def update(self, error, dt):
        self.integral += error * dt
        deriv = (error - self.last_err) / dt if dt > 0 else 0.0
        self.last_err = error
        return (self.p * error) + (self.i * self.integral) + (self.d * deriv)

# =========================
# INICIALIZAÇÃO
# =========================
print("=" * 60)
print("  AIMBOT — FINS EDUCACIONAIS")
print("=" * 60)

SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_resolution()
print(f"Resolução: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")

# Detectar porta e iniciar thread serial
arduino_port = find_arduino_port()
t_serial = threading.Thread(target=serial_worker, args=(arduino_port,), daemon=True)
t_serial.start()

try:
    sct = mss()
except Exception as e:
    print("Erro ao iniciar mss:", e); sys.exit()

pid_x = PID(0.3, 0.05, 0.1)
pid_y = PID(0.3, 0.05, 0.1)

monitor = {
    "top":    SCREEN_HEIGHT // 2 - FOV_SIZE // 2,
    "left":   SCREEN_WIDTH  // 2 - FOV_SIZE // 2,
    "width":  FOV_SIZE,
    "height": FOV_SIZE,
}
print(f"FOV: {monitor}")
print("Pressione CTRL+C para parar.")
if SHOW_DEBUG_WINDOW:
    print("Pressione Q na janela de debug para fechar.\n")

last_time     = time.time()
last_detected = False

# =========================
# LOOP PRINCIPAL  (apenas visão — serial em thread separada)
# =========================
try:
    while True:
        # ── Captura ──────────────────────────────────────────────
        img     = np.array(sct.grab(monitor))
        img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR) if img.shape[2] == 4 else img

        # ── Máscara HSV ───────────────────────────────────────────
        hsv  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, PURPLE_LOWER, PURPLE_UPPER)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        center_x    = FOV_SIZE // 2
        center_y    = FOV_SIZE // 2
        debug_frame = img_bgr.copy()
        cv2.circle(debug_frame, (center_x, center_y), 5, (0, 255, 0), -1)

        detected  = False
        area_text = "Area: 0"

        if contours:
            c    = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(c)
            area_text = f"Area: {area:.1f}"

            if area > 20:
                M = cv2.moments(c)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])

                    now = time.time()
                    dt  = max(now - last_time, 1e-4)

                    err_x = cx - center_x
                    err_y = cy - center_y

                    move_x = pid_x.update(err_x, dt)
                    move_y = pid_y.update(err_y, dt)

                    move_x = max(-MAX_MOVE, min(MAX_MOVE, move_x))
                    move_y = max(-MAX_MOVE, min(MAX_MOVE, move_y))

                    # ── Enfileira movimento (não bloqueia) ────────
                    move_mouse(move_x, move_y)

                    last_time = now
                    detected  = True

                    x, y, w, h = cv2.boundingRect(c)
                    cv2.rectangle(debug_frame, (x, y), (x+w, y+h), (255, 0, 255), 2)
                    cv2.circle(debug_frame, (cx, cy), 6, (0, 0, 255), -1)
                    cv2.line(debug_frame, (center_x, center_y), (cx, cy), (255, 255, 0), 2)

                    if PRINT_DEBUG and not last_detected:
                        print("=" * 60)
                        print("ALVO DETECTADO")
                        print(f"  Área    : {area:.1f}")
                        print(f"  Centro  : ({cx}, {cy})")
                        print(f"  Erro    : X={err_x}  Y={err_y}")
                        print(f"  PID     : X={move_x:.2f}  Y={move_y:.2f}")
                        print(f"  Serial  : Δx={int(move_x)}  Δy={int(move_y)}")

        # ── HUD ──────────────────────────────────────────────────
        cv2.putText(debug_frame, area_text, (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        status_label = "STATUS: RASTREANDO" if detected else "STATUS: SEM ALVO"
        status_color = (0, 255, 0)          if detected else (0, 0, 255)
        cv2.putText(debug_frame, status_label, (10, FOV_SIZE - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)

        last_detected = detected

        # ── Janelas de debug ──────────────────────────────────────
        if SHOW_DEBUG_WINDOW:
            cv2.imshow("Captura Central", debug_frame)
            cv2.imshow("Mascara HSV",     mask)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("Encerrado pelo usuário (tecla Q).")
                break

        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nScript encerrado pelo usuário (CTRL+C).")
except Exception as e:
    print("\nErro inesperado:", e)
finally:
    serial_thread_running = False
    t_serial.join(timeout=2)
    cv2.destroyAllWindows()
    print("Finalizado.")
