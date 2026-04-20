#include <SPI.h>
#include <Usb.h>
#include <usbhub.h>
#include <hiduniversal.h>
#include <Mouse.h>

USB Usb;
USBHub Hub(&Usb);
HIDUniversal Hid(&Usb);

// Ajuste a sensibilidade aqui. Se travar, tente 1.0 primeiro.
float sensibilidadeFinal = 0.05; 

class HighResParser : public HIDReportParser {
public:
  void Parse(USBHID *hid, bool is_rpt_id, uint8_t len, uint8_t *buf) {
    uint8_t off = is_rpt_id ? 1 : 0;
    
    // Se len for menor que 4, o pacote é inválido para mouse gamer
    if (len < off + 3) return;

    // 1. BOTÕES (Mais estável)
    uint8_t buttons = buf[off + 0];
    static uint8_t last_buttons = 0;
    if (buttons != last_buttons) {
      if (buttons & 0x01) Mouse.press(MOUSE_LEFT);   else Mouse.release(MOUSE_LEFT);
      if (buttons & 0x02) Mouse.press(MOUSE_RIGHT);  else Mouse.release(MOUSE_RIGHT);
      if (buttons & 0x04) Mouse.press(MOUSE_MIDDLE); else Mouse.release(MOUSE_MIDDLE);
      last_buttons = buttons;
    }

    // 2. MOVIMENTO 
    // Voltando para 8-bit simples primeiro para garantir que o Shield não trave por processamento
    int8_t mX = (int8_t)buf[off + 1];
    int8_t mY = (int8_t)buf[off + 2];

    if (mX != 0 || mY != 0) {
      Mouse.move(mX, mY, 0);
    }
    
    // 3. SCROLL DESATIVADO PARA TESTE DE ESTABILIDADE
    // Se o mouse travar, o problema costuma ser o parser tentando ler bytes inexistentes.
  }
};

HighResParser Prs;

#define PACKET_SIZE 4
uint8_t serialBuf[PACKET_SIZE];
uint8_t serialIdx = 0;

void setup() {
  Serial.begin(115200);
  Mouse.begin();

  // Se travar aqui, o Shield está com defeito ou sem energia
  if (Usb.Init() == -1) {
    Serial.println("Erro USB Host");
    while (1); 
  }

  delay(200);
  Hid.SetReportParser(0, &Prs);
  Serial.println("Sistema Pronto");
}

void loop() {
  Usb.Task();

  // Processamento Serial mais leve
  if (Serial.available() > 0) {
    uint8_t b = Serial.read();
    serialBuf[serialIdx++] = b;

    if (serialIdx == PACKET_SIZE) {
      int16_t dx = (int16_t)(serialBuf[0] | (serialBuf[1] << 8));
      int16_t dy = (int16_t)(serialBuf[2] | (serialBuf[3] << 8));
      
      // Move o mouse em um único passo para não segurar o loop
      int8_t sx = constrain(dx, -127, 127);
      int8_t sy = constrain(dy, -127, 127);
      Mouse.move(sx, sy, 0);
      
      serialIdx = 0;
    }
  }
}