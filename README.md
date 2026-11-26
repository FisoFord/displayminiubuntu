# Mini display USB en Linux

Guía y utilidades para usar en Linux el mini display USB de 3.5" que venía
funcionando con software de Windows (`UsbMonitor.exe` / AIDA64).

## 1. Qué pantalla es

Identificada en este equipo:

| Dato | Valor |
|---|---|
| USB ID | `1a86:5722` (WCH / CH340 en modo CDC-ACM) |
| Número de serie | `USB35INCHIPSV2` |
| Puerto en Windows | `COM3` — "USB Serial Device" |
| Respuesta al comando HELLO | `01 01 01 01 01 01` |
| Modelo | Turing Smart Screen **Rev A** / clon `UsbPCMonitor 3.5"` |
| Resolución | 320 × 480 (vertical), RGB565 |

En Linux **no hace falta instalar ningún driver**: el kernel la reconoce con
`cdc_acm` y aparece como `/dev/ttyACM0`. Lo que falta es el programa que habla
su protocolo, porque `UsbMonitor.exe` es una aplicación Win32/.NET sin versión
Linux.

La solución es el proyecto open-source
[`turing-smart-screen-python`](https://github.com/mathoudebine/turing-smart-screen-python),
que soporta exactamente esta revisión y corre en Linux, Windows y macOS.
Además incluye temas, sensores de CPU/GPU/RAM/disco/red, gráficas y arranque
automático.

> Estado verificado: la pantalla responde al protocolo y muestra imágenes
> desde este equipo con `minidisplay.py` (mismo código que se usa en Linux).

## 2. Instalación en Linux (recomendado)

Requisitos: Linux con systemd (Ubuntu, Debian, Fedora, Arch...), Python 3.9+,
conexión a internet.

```bash
# copia la carpeta linux/ al equipo Linux y entra en ella
chmod +x install.sh
./install.sh
```

El instalador:

1. instala `python3-venv`, `tk`, `git` y dependencias;
2. descarga el proyecto en `/opt/turing-smart-screen` y crea un entorno virtual;
3. deja `config.yaml` listo para la revisión A (tema `3.5inchTheme2`, brillo 20 %);
4. añade una regla udev que crea `/dev/turing-screen` accesible sin root;
5. desactiva `brltty` si está presente (se queda con este chip CH340);
6. crea y arranca el servicio `turing-smart-screen`.

Usa la versión `3.10.0` (probada con esta pantalla). Para la última de `main`:
`REF=main ./install.sh`.

Al terminar, **cierra sesión y vuelve a entrar** para que tu usuario tome el
grupo `dialout` (o ejecuta `newgrp dialout` en la terminal actual).

Comprobación rápida:

```bash
ls -l /dev/turing-screen
systemctl status turing-smart-screen
tail -f /opt/turing-smart-screen/log.log
```

Opciones:

```bash
./install.sh --no-service    # instalar sin systemd
./install.sh --keep-brltty   # conservar brltty (lectores Braille)
INSTALL_DIR=$HOME/turing ./install.sh
```

### Ubuntu Server (sin entorno gráfico)

El monitor funciona igual en un servidor: no necesita servidor X ni
escritorio. Ten en cuenta:

- No habrá icono de bandeja; se controla con `systemctl` y `log.log`.
- `configure.py` (asistente gráfico) no arranca sin pantalla. El instalador ya
  deja `config.yaml` preparado; para cambiar tema o brillo edita ese archivo, o
  usa `minidisplay.py --brightness`.
- Temperaturas de CPU: `sudo apt install lm-sensors && sudo sensors-detect --auto`
  (psutil lee `/sys/class/hwmon` directamente, pero así puedes verificarlas con
  `sensors`).
- GPU integrada Intel: el proyecto no publica %/temperatura de iGPU en Linux;
  esos campos del tema saldrán a 0 o N/A. CPU, RAM, disco, red y fecha sí
  funcionan.
- El servicio usa `Restart=always` a propósito: si arranca antes de que el USB
  esté listo, el programa termina y systemd lo relanza hasta encontrarlo.

### Instalación manual

```bash
sudo apt install python3-venv python3-tk git
git clone --depth 1 https://github.com/mathoudebine/turing-smart-screen-python.git
cd turing-smart-screen-python
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Edita `config.yaml`:

```yaml
config:
  COM_PORT: "AUTO"          # o "/dev/turing-screen"
  THEME: 3.5inchTheme2
display:
  REVISION: A
  BRIGHTNESS: 20
  RESET_ON_STARTUP: false
```

Regla udev (opcional, para no usar `sudo`):

```bash
sudo tee /etc/udev/rules.d/99-turing-smart-screen.rules >/dev/null <<'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", \
    SYMLINK+="turing-screen", GROUP="dialout", MODE="0660", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG dialout "$USER"
```

Y arranca:

```bash
.venv/bin/python main.py
```

### Arranque automático

El instalador ya crea `/etc/systemd/system/turing-smart-screen.service`.
Para hacerlo a mano, con `User=tuusuario` y `WorkingDirectory=/opt/turing-smart-screen`:

```ini
[Unit]
Description=Turing Smart Screen system monitor
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=tuusuario
WorkingDirectory=/opt/turing-smart-screen
ExecStart=/opt/turing-smart-screen/.venv/bin/python /opt/turing-smart-screen/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp turing-smart-screen.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now turing-smart-screen
```

## 3. Driver mínimo (`minidisplay.py`)

Utilidad autónoma de ~300 líneas para probar el panel o mostrar imágenes
concretas. Solo necesita `pyserial` y `pillow`, sirve igual en Linux y Windows.

```bash
python3 -m pip install --user pyserial pillow

python3 minidisplay.py --info
python3 minidisplay.py --test
python3 minidisplay.py --image foto.png
python3 minidisplay.py --image foto.png --orientation landscape
python3 minidisplay.py --brightness 15
python3 minidisplay.py --clear
python3 minidisplay.py --off
python3 minidisplay.py --on
python3 minidisplay.py --port /dev/ttyACM0 --test
```

En Windows, para comprobar el hardware sin el software del fabricante:

```powershell
python minidisplay.py --port COM3 --test
```

### Usarlo desde tu propio código

```python
from PIL import Image
from minidisplay import MiniDisplay

with MiniDisplay() as lcd:          # autodetecta /dev/ttyACM* o COMx
    lcd.set_orientation("landscape")
    lcd.set_brightness(30)
    lcd.show(Image.open("imagen.png").resize(lcd.get_size()))
```

## 4. Panel web: diseños, fondos y servicios

`webapp/` es un servicio web para la red local que sustituye al monitor por
consola: permite subir una **serie de imágenes** como marca de agua rotatoria,
elegir entre **cuatro diseños** cómo se muestran CPU/RAM/RED y ver una
página **tipo Proxmox** con los servicios de systemd (y contenedores Docker).

### Qué incluye

- **Cuatro diseños fijos** que se eligen con un check: **Proxmox**, **Minimal**,
  **Neón** y **Clásico**. Cada miniatura se genera con tu fondo y tus datos
  actuales, así ves el resultado antes de elegirlo.
  - **Proxmox**: anillos CPU/RAM, red, disco y lista de servicios.
  - **Minimal**: CPU grande, RAM, red y temperatura; arriba hora grande con fecha
    y nombre del equipo, y abajo dos columnas de servicios y contenedores.
  - **Neón**: anillos CPU/temperatura y gráficas históricas.
  - **Clásico**: barras CPU/RAM/disco, gráfica de red y resumen de texto.
- **Fondos por defecto**: el proyecto incluye 5 imágenes en `webapp/defaults/`
  (`circuito-fondo`, `heroes`, `torre`, `luna`, `tigre`). En una instalación
  nueva se copian solas y quedan seleccionadas; no hay que subir nada.
- **Fondos**: subida múltiple, rotación cada N segundos, opacidad, desenfoque,
  tinte, degradado inferior y ajuste (cubrir/contener/estirar).
- Cada diseño incluye su propia combinación de anillos, barras, gráficas
  históricas, números grandes, reloj, host y lista de servicios.
- **Servicios**: estado de systemd y Docker, CPU/RAM por unidad, filtros y
  acciones de arrancar/detener/reiniciar (opcionales).
- **Sin entorno gráfico**: no necesita X; todo se controla desde el navegador.
- Salida al panel USB con reconexión automática y brillo configurable.

### Instalación desde GitHub

```bash
sudo apt install -y git
git clone https://github.com/TU_USUARIO/TU_REPO.git ~/driverMiniDisplay
cd ~/driverMiniDisplay/webapp
chmod +x install.sh
sudo ./install.sh --actions
```

Para actualizar más adelante:

```bash
cd ~/driverMiniDisplay
git pull
sudo ./webapp/install.sh --actions
```

Los datos de `/var/lib/minidisplay-web` (configuración, fondos y logs) se
conservan entre actualizaciones.

### Alternativa: copiar desde Windows sin GitHub

**1. Copiar el proyecto desde Windows** (sin el entorno virtual local):

```powershell
tar -czf driverMiniDisplay.tgz --exclude=.venv --exclude=webapp/data `
    --exclude=__pycache__ minidisplay.py linux webapp README.md
scp .\driverMiniDisplay.tgz usuario@IP_DEL_SERVIDOR:/home/usuario/
```

También vale `scp -r D:\Proyectos\driverMiniDisplay usuario@IP_DEL_SERVIDOR:/home/usuario/`
y luego borrar `.venv` en el servidor.

**2. Instalar en Ubuntu**:

```bash
tar -xzf driverMiniDisplay.tgz
cd webapp
chmod +x install.sh
sudo ./install.sh --actions      # --actions = permitir start/stop/restart
```

Abre `http://IP_DEL_SERVIDOR:8080`. Si hay firewall:

```bash
sudo ufw allow 8080/tcp
```

El instalador copia la app a `/opt/minidisplay-web`, crea su venv, los datos en
`/var/lib/minidisplay-web`, la regla udev y el servicio `minidisplay-web`.
En el primer arranque se aplica el diseño **Minimal** y se añaden las 5
imágenes por defecto.

> Importante: el panel solo puede tener un programa hablando por el puerto
> serie. Desenchúfalo del Windows antes de conectarlo al servidor. El instalador
> detiene `turing-smart-screen` si estaba activo (usa `--keep-monitor` para no
> hacerlo).

### Primeros pasos

1. **Diseño del panel**: elige uno de los cuatro estilos con un check. Una
   instalación nueva arranca con **Minimal**. La miniatura ya muestra tu fondo y
   tus datos; el panel cambia en ~1 segundo.
2. **Fondo**: sube imágenes (o arrástralas) y marca las que quieras en la
   rotación. Ajusta opacidad/tinte hasta que los datos se lean bien.
3. Ajusta el **brillo** (20–50 % recomendado) y el refresco.
4. **Servicios**: marca en la columna “Panel” las unidades que quieres ver en el
   widget de servicios (solo el diseño **Proxmox** incluye esa lista). El resto
   de la página muestra CPU, RAM, disco, red, uptime y el estado de cada unidad
   y contenedor.

Los cambios se guardan solos en el servidor (`config.json`) y se aplican al
panel en el siguiente frame (1 fps por defecto). El botón **Enviar ahora** fuerza
un envío.

### Autenticación

Por defecto no pide contraseña (red local). Para activarla, edita
`/etc/default/minidisplay-web`:

```ini
WEBAPP_USER=admin
WEBAPP_PASSWORD=una-clave-larga
```

y ejecuta `sudo systemctl restart minidisplay-web`.

### Acciones sobre servicios

Con `--actions` se crea `/etc/sudoers.d/minidisplay-web`, que permite al usuario
del servicio ejecutar únicamente `systemctl start|stop|restart|enable|disable`
(y lo mismo con `docker`). Sin ese archivo la página es de solo lectura y lo
indica en un aviso. Revisa el archivo si quieres limitarlo a unidades concretas.

### API (por si quieres automatizar)

```
GET  /api/config              configuración actual
PUT  /api/config              guardar configuración
GET  /api/state               métricas + estado del panel
GET  /api/preview.png         frame actual
POST /api/display/push        forzar envío
GET  /api/backgrounds         imágenes subidas
POST /api/backgrounds         subir (multipart, campo "files")
GET  /api/services            systemd + docker
POST /api/services/action     {scope,name,action}
GET  /api/health              diagnóstico
GET  /api/logs?lines=150      últimas líneas del log
```

### Problemas frecuentes del panel web

- **El servicio no arranca**: `journalctl -u minidisplay-web -n 80`.
- **“panel sin conexión”**: otro proceso usa el puerto serie, el usuario no está
  en `dialout` o el cable es solo de carga. Prueba
  `python3 minidisplay.py --info`.
- **Docker no aparece**: el usuario necesita el grupo `docker` o `--actions`.
- **Cambiar puerto**: `sudo ./install.sh --port 9000` (y abre el firewall).
- **Desinstalar**:

```bash
sudo systemctl disable --now minidisplay-web
sudo rm /etc/systemd/system/minidisplay-web.service /etc/default/minidisplay-web
sudo rm -f /etc/sudoers.d/minidisplay-web
sudo rm -rf /opt/minidisplay-web /var/lib/minidisplay-web
```

## 5. Problemas frecuentes

**No aparece `/dev/ttyACM0`**
- Prueba otro cable USB (muchos cables solo cargan).
- `dmesg | tail -20` debe mostrar `cdc_acm`.
- En WSL2 el USB no se comparte por defecto: usa Linux nativo o `usbipd-win`
  (el driver serie por USB/IP no es fiable). Mejor Linux nativo.

**El puerto existe pero no hay permiso**
```bash
sudo usermod -aG dialout "$USER"   # y reinicia sesión
# en Arch/Manjaro el grupo es uucp: sudo usermod -aG uucp "$USER"
# alternativa puntual:
sudo chmod 666 /dev/ttyACM0
```

**El display se queda en negro o `brltty` lo bloquea**
```bash
# Ubuntu/Debian modernos
sudo systemctl stop brltty-udev.service brltty.service
sudo systemctl mask brltty-udev.service brltty.service brltty@.service
# si no usas lector Braille, lo mas simple:
sudo apt remove brltty
# comprueba que el chip aparece:
lsusb | grep 1a86
dmesg | grep -i cdc_acm
```

**Se ve girado / recortado**
El panel es vertical (320×480). `SetOrientation("landscape")` lo gira a
480×320. El tema debe ser del mismo tamaño (`DISPLAY_SIZE` en `theme.yaml`).

**Se calienta**
Es normal en la revisión A. Mantén `BRIGHTNESS` en 20–50 % y no lo alimentes
con un cargador que no sea el suyo.

**La pantalla se reinicia al arrancar**
En la revisión A el comando de reset hace desaparecer el puerto unos segundos.
Deja `RESET_ON_STARTUP: false` (el instalador ya lo hace) y `COM_PORT: AUTO`.

**Quiero usar el software original de Windows**
No existe versión Linux de `UsbMonitor.exe`/AIDA64 para este panel y es
cerrado. No hay forma de ejecutarlo de forma fiable con Wine porque accede al
puerto serie y a sensores del sistema. La alternativa soportada es este
proyecto, con temas muy similares a los del fabricante.

## 6. Estructura del proyecto

```
driverMiniDisplay/
├── minidisplay.py          # driver mínimo + CLI (Linux/Windows/macOS)
├── linux/
│   ├── install.sh          # monitor clásico todo-en-uno
│   └── 99-turing-smart-screen.rules
├── webapp/                 # panel web (editor + servicios)
│   ├── app.py              # Flask: API y páginas
│   ├── config.py           # ajustes, diseños y definición de widgets
│   ├── collect.py          # métricas con psutil
│   ├── render.py           # composición del frame 320x480
│   ├── services.py         # systemd + Docker
│   ├── engine.py           # hilo de render
│   ├── display.py          # hilo de envío al panel
│   ├── templates/index.html
│   ├── static/{app.js,style.css}
│   ├── defaults/           # 5 fondos incluidos de serie
│   ├── requirements.txt
│   └── install.sh
└── README.md
```

## 7. Desinstalar

```bash
sudo systemctl disable --now turing-smart-screen
sudo rm /etc/systemd/system/turing-smart-screen.service
sudo rm /etc/udev/rules.d/99-turing-smart-screen.rules
sudo rm -rf /opt/turing-smart-screen
sudo systemctl unmask brltty-udev.service brltty.service    # si lo desactivaste
```

## Créditos

- [`turing-smart-screen-python`](https://github.com/mathoudebine/turing-smart-screen-python) — Matthieu Houdebine, GPL-3.0.
- Protocolo de la revisión A documentado por la comunidad (Hackaday, CNX Software).
