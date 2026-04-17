"""
Valorant Aimbot - Interception Driver
=====================================
Usa o driver Interception para mover o mouse no nível do kernel,
contornando as proteções do Vanguard.

Requisitos:
- Interception driver instalado (install-interception.exe /install + reiniciar PC)
- pip install interception-python
- pip install numpy mss keyboard

Uso:
- Executar como ADMINISTRADOR
- Pressione F1 para ativar/desativar
- Pressione F2 para sair
- Segure o botão direito do mouse para ativar o aimbot (modo ADS)
"""

import numpy as np
import mss
import time
import keyboard
import ctypes
import sys
import os

# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Cor do inimigo (roxo/magenta do destaque do Valorant)
# Ajuste esses valores conforme necessário
TARGET_COLOR_LOWER = np.array([140, 50, 140])   # BGR mínimo
TARGET_COLOR_UPPER = np.array([200, 120, 255])   # BGR máximo

# Alternativa: cor amarela (outline amarelo)
# TARGET_COLOR_LOWER = np.array([0, 180, 180])
# TARGET_COLOR_UPPER = np.array([80, 255, 255])

# Região de captura (centro da tela)
CAPTURE_WIDTH = 120    # Largura da região de captura
CAPTURE_HEIGHT = 120   # Altura da região de captura

# Sensibilidade e suavização
SMOOTHING = 3.0        # Quanto maior, mais suave (mais lento). 1.0 = direto
SPEED_FACTOR = 1.0     # Multiplicador de velocidade. 1.0 = normal
MIN_PIXELS = 15        # Mínimo de pixels para considerar como alvo
DEADZONE = 3           # Pixels de deadzone (ignora movimentos muito pequenos)

# Offset vertical (mira na cabeça) - negativo = mais pra cima
HEAD_OFFSET_Y = -8

# Teclas
TOGGLE_KEY = 'F1'      # Ativar/desativar
EXIT_KEY = 'F2'        # Sair
ADS_MODE = True        # True = só funciona com botão direito pressionado

# FPS limit
TARGET_FPS = 120

# ============================================================
# INTERCEPTION SETUP
# ============================================================

try:
    import interception
    INTERCEPTION_AVAILABLE = True
    print("[OK] Interception driver carregado com sucesso!")
except ImportError:
    INTERCEPTION_AVAILABLE = False
    print("[ERRO] interception-python não encontrado!")
    print("       Instale com: pip install interception-python")
    print("       Certifique-se que o driver Interception está instalado e o PC foi reiniciado.")

# ============================================================
# FALLBACK: ctypes mouse_event (caso Interception falhe)
# ============================================================

MOUSEEVENTF_MOVE = 0x0001

def move_mouse_fallback(dx, dy):
    """Move o mouse usando ctypes (fallback)"""
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)

# ============================================================
# INTERCEPTION MOUSE MOVEMENT
# ============================================================

class InterceptionMouse:
    """Classe para mover o mouse usando o Interception driver"""
    
    def __init__(self):
        self.ctx = None
        self.mouse_device = None
        self.initialized = False
        
    def initialize(self):
        """Inicializa o Interception context e encontra o dispositivo do mouse"""
        if not INTERCEPTION_AVAILABLE:
            print("[ERRO] Interception não disponível")
            return False
            
        try:
            self.ctx = interception.auto_capture_devices(keyboard=False, mouse=True)
            self.initialized = True
            print("[OK] Interception mouse inicializado!")
            print(f"     Context: {self.ctx}")
            return True
        except Exception as e:
            print(f"[ERRO] Falha ao inicializar Interception: {e}")
            
            # Tentar método alternativo
            try:
                print("[INFO] Tentando método alternativo de inicialização...")
                ctx = interception.Interception()
                ctx.set_filter(interception.is_mouse, interception.INTERCEPTION_FILTER_MOUSE_ALL)
                self.ctx = ctx
                self.initialized = True
                print("[OK] Interception inicializado (método alternativo)!")
                return True
            except Exception as e2:
                print(f"[ERRO] Método alternativo também falhou: {e2}")
                return False
    
    def move(self, dx, dy):
        """Move o mouse relativamente usando Interception"""
        if not self.initialized:
            move_mouse_fallback(dx, dy)
            return
            
        try:
            interception.move_relative(int(dx), int(dy))
        except AttributeError:
            try:
                # Método alternativo
                stroke = interception.MouseStroke(
                    interception.INTERCEPTION_MOUSE_MOVE_RELATIVE,
                    0, 0, 0, int(dx), int(dy)
                )
                if self.mouse_device:
                    self.ctx.send(self.mouse_device, stroke)
                else:
                    interception.move_relative(int(dx), int(dy))
            except Exception:
                move_mouse_fallback(dx, dy)
        except Exception:
            move_mouse_fallback(dx, dy)
    
    def cleanup(self):
        """Limpa os recursos do Interception"""
        if self.ctx:
            try:
                del self.ctx
            except:
                pass

# ============================================================
# DETECÇÃO DE ALVO
# ============================================================

def get_screen_center():
    """Retorna o centro da tela"""
    user32 = ctypes.windll.user32
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return w // 2, h // 2

def find_target(frame, center_x, center_y, region_left, region_top):
    """
    Encontra o alvo na imagem capturada.
    Retorna (dx, dy, pixel_count) ou None se não encontrar.
    """
    # Converter para numpy array BGR
    img = np.array(frame)[:, :, :3]  # Remove alpha se existir
    
    # Criar máscara de cor
    mask = np.all(
        (img >= TARGET_COLOR_LOWER) & (img <= TARGET_COLOR_UPPER),
        axis=2
    )
    
    # Contar pixels
    pixel_count = np.sum(mask)
    
    if pixel_count < MIN_PIXELS:
        return None
    
    # Encontrar centroide dos pixels detectados
    coords = np.where(mask)
    if len(coords[0]) == 0:
        return None
    
    target_y = np.mean(coords[0])  # Média Y
    target_x = np.mean(coords[1])  # Média X
    
    # Calcular deslocamento relativo ao centro da tela
    # A região capturada começa em (region_left, region_top)
    abs_target_x = region_left + target_x
    abs_target_y = region_top + target_y
    
    dx = abs_target_x - center_x
    dy = abs_target_y - center_y + HEAD_OFFSET_Y
    
    return dx, dy, pixel_count

# ============================================================
# VERIFICAR BOTÃO DIREITO DO MOUSE
# ============================================================

def is_right_mouse_pressed():
    """Verifica se o botão direito do mouse está pressionado"""
    return ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000 != 0

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print("=" * 60)
    print("  VALORANT AIMBOT - INTERCEPTION DRIVER")
    print("=" * 60)
    print()
    
    # Verificar admin
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False
    
    if not is_admin:
        print("[AVISO] NÃO está rodando como Administrador!")
        print("        O Interception PRECISA de privilégios de admin.")
        print("        Feche e abra o CMD como Administrador.")
        print()
    else:
        print("[OK] Rodando como Administrador")
    
    # Inicializar Interception
    mouse = InterceptionMouse()
    use_interception = mouse.initialize()
    
    if not use_interception:
        print()
        print("[AVISO] Interception não funcionou. Usando fallback (mouse_event).")
        print("        O fallback provavelmente NÃO vai funcionar no Valorant.")
        print()
        print("Verifique:")
        print("  1. O driver Interception está instalado? (install-interception.exe /install)")
        print("  2. Você reiniciou o PC depois de instalar?")
        print("  3. pip install interception-python está instalado?")
        print()
    
    # Obter centro da tela
    center_x, center_y = get_screen_center()
    print(f"[INFO] Centro da tela: ({center_x}, {center_y})")
    print(f"[INFO] Região de captura: {CAPTURE_WIDTH}x{CAPTURE_HEIGHT}")
    print(f"[INFO] Cor alvo BGR: {TARGET_COLOR_LOWER} - {TARGET_COLOR_UPPER}")
    print(f"[INFO] Suavização: {SMOOTHING}")
    print(f"[INFO] Modo ADS: {'SIM (segure botão direito)' if ADS_MODE else 'NÃO (sempre ativo)'}")
    print()
    print(f"[TECLAS] {TOGGLE_KEY} = Ativar/Desativar | {EXIT_KEY} = Sair")
    print()
    
    # Região de captura
    region = {
        'left': center_x - CAPTURE_WIDTH // 2,
        'top': center_y - CAPTURE_HEIGHT // 2,
        'width': CAPTURE_WIDTH,
        'height': CAPTURE_HEIGHT
    }
    
    # Estado
    enabled = True
    running = True
    frame_count = 0
    fps = 0
    fps_timer = time.time()
    move_count = 0
    method_name = "INTERCEPTION" if use_interception else "FALLBACK (mouse_event)"
    
    print(f"[ATIVO] Aimbot LIGADO | Método: {method_name}")
    print("-" * 60)
    
    # Registrar teclas
    def toggle():
        nonlocal enabled
        enabled = not enabled
        status = "LIGADO" if enabled else "DESLIGADO"
        print(f"\n[{TOGGLE_KEY}] Aimbot {status}")
    
    def exit_program():
        nonlocal running
        running = False
        print(f"\n[{EXIT_KEY}] Saindo...")
    
    keyboard.on_press_key(TOGGLE_KEY, lambda _: toggle())
    keyboard.on_press_key(EXIT_KEY, lambda _: exit_program())
    
    # Loop principal
    sct = mss.mss()
    frame_time = 1.0 / TARGET_FPS
    
    try:
        while running:
            loop_start = time.time()
            
            # Calcular FPS
            frame_count += 1
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count = 0
                fps_timer = time.time()
            
            # Verificar se está ativo
            if not enabled:
                time.sleep(0.01)
                continue
            
            # Verificar ADS (botão direito)
            if ADS_MODE and not is_right_mouse_pressed():
                # Mostrar status sem mover
                print(f"\r[AGUARDANDO] Segure botão direito para ativar | FPS:{fps:.0f} | Moves:{move_count}", end="", flush=True)
                time.sleep(0.005)
                continue
            
            # Capturar tela
            frame = sct.grab(region)
            
            # Encontrar alvo
            result = find_target(frame, center_x, center_y, region['left'], region['top'])
            
            if result is not None:
                dx, dy, pixel_count = result
                
                # Aplicar deadzone
                if abs(dx) < DEADZONE and abs(dy) < DEADZONE:
                    print(f"\r[MIRA OK] No alvo | PX:{pixel_count} | FPS:{fps:.0f} | Moves:{move_count}    ", end="", flush=True)
                    continue
                
                # Suavizar movimento
                move_x = (dx / SMOOTHING) * SPEED_FACTOR
                move_y = (dy / SMOOTHING) * SPEED_FACTOR
                
                # Limitar movimento máximo por frame
                max_move = 50
                move_x = max(-max_move, min(max_move, move_x))
                move_y = max(-max_move, min(max_move, move_y))
                
                # Mover mouse
                if use_interception:
                    mouse.move(move_x, move_y)
                else:
                    move_mouse_fallback(move_x, move_y)
                
                move_count += 1
                
                print(f"\r[ALVO] dx:{dx:+.1f} dy:{dy:+.1f} -> mov:({move_x:+.1f},{move_y:+.1f}) | PX:{pixel_count} | FPS:{fps:.0f} | Moves:{move_count}", end="", flush=True)
            else:
                print(f"\r[BUSCANDO] Sem alvo | FPS:{fps:.0f} | Moves:{move_count}                        ", end="", flush=True)
            
            # Limitar FPS
            elapsed_frame = time.time() - loop_start
            if elapsed_frame < frame_time:
                time.sleep(frame_time - elapsed_frame)
                
    except KeyboardInterrupt:
        print("\n\n[CTRL+C] Interrompido pelo usuário")
    finally:
        mouse.cleanup()
        keyboard.unhook_all()
        print("\n[FIM] Aimbot encerrado.")
        print(f"[STATS] Total de movimentos: {move_count}")

# ============================================================
# MENU INICIAL
# ============================================================

if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║     VALORANT AIMBOT - INTERCEPTION DRIVER           ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║                                                      ║")
    print("║  [1] Iniciar Aimbot (Interception)                   ║")
    print("║  [2] Testar movimento do mouse                       ║")
    print("║  [3] Configurações atuais                            ║")
    print("║  [4] Sair                                            ║")
    print("║                                                      ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    
    choice = input("Escolha uma opção: ").strip()
    
    if choice == "1":
        print()
        main()
        
    elif choice == "2":
        print()
        print("[TESTE] Testando movimento do mouse com Interception...")
        print("        O mouse vai se mover em 3 segundos.")
        print("        Observe se o cursor se move na tela.")
        print()
        
        mouse = InterceptionMouse()
        success = mouse.initialize()
        
        if success:
            print("[OK] Interception inicializado. Movendo em 3 segundos...")
            time.sleep(3)
            
            # Teste: mover em quadrado
            movements = [
                ("Direita", 50, 0),
                ("Baixo", 0, 50),
                ("Esquerda", -50, 0),
                ("Cima", 0, -50),
            ]
            
            for name, dx, dy in movements:
                print(f"  Movendo: {name} ({dx}, {dy})")
                for i in range(10):
                    mouse.move(dx // 10, dy // 10)
                    time.sleep(0.02)
                time.sleep(0.3)
            
            print()
            print("[RESULTADO] O mouse se moveu?")
            print("  Se SIM -> O Interception está funcionando! Use opção 1.")
            print("  Se NÃO -> Verifique a instalação do driver.")
            mouse.cleanup()
        else:
            print("[ERRO] Não foi possível inicializar o Interception.")
            print("       Verifique a instalação do driver e reinicie o PC.")
            
    elif choice == "3":
        print()
        print("=== CONFIGURAÇÕES ATUAIS ===")
        print(f"  Cor alvo (BGR min): {TARGET_COLOR_LOWER}")
        print(f"  Cor alvo (BGR max): {TARGET_COLOR_UPPER}")
        print(f"  Região de captura:  {CAPTURE_WIDTH}x{CAPTURE_HEIGHT}")
        print(f"  Suavização:         {SMOOTHING}")
        print(f"  Velocidade:         {SPEED_FACTOR}")
        print(f"  Min pixels:         {MIN_PIXELS}")
        print(f"  Deadzone:           {DEADZONE}")
        print(f"  Head offset Y:      {HEAD_OFFSET_Y}")
        print(f"  Modo ADS:           {ADS_MODE}")
        print(f"  FPS alvo:           {TARGET_FPS}")
        print()
        print("Para alterar, edite as variáveis no início do arquivo.")
        
    elif choice == "4":
        print("Saindo...")
        sys.exit(0)
    else:
        print("Opção inválida!")