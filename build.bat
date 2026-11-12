@echo off
setlocal
rem ============================================================
rem  Build EpsonInkPadReset.exe
rem  ต้องมี: Python 3.10+ (คำสั่ง py), git, curl (มากับ Windows 10/11)
rem ============================================================
cd /d "%~dp0"
if not defined PYTHON set PYTHON=py

set EPC_COMMIT=2dc3bebacf314f22bd6484acdb2a7434c7cc00ad
set TOML_URL=https://codeberg.org/atufi/reinkpy/raw/branch/main/reinkpy/epson.toml

if not exist vendor mkdir vendor
if not exist vendor\epson_print_conf (
    echo [1/5] Downloading epson_print_conf...
    git -c http.sslBackend=schannel clone https://github.com/Ircama/epson_print_conf.git vendor\epson_print_conf || goto :error
)
git -C vendor\epson_print_conf -c http.sslBackend=schannel fetch --quiet origin %EPC_COMMIT% 2>nul
git -C vendor\epson_print_conf checkout --quiet %EPC_COMMIT% || goto :error

if not exist venv (
    echo [2/5] Creating virtual environment...
    %PYTHON% -m venv venv || goto :error
)
echo [3/5] Installing packages...
venv\Scripts\python -m pip install --quiet -r vendor\epson_print_conf\requirements.txt pyinstaller customtkinter==5.2.2 pywebview==6.2.1 || goto :error

echo [4/5] Building printer database...
curl.exe -sSL -o vendor\epson.toml %TOML_URL% || goto :error
venv\Scripts\python vendor\epson_print_conf\parse_devices.py -T -c vendor\epson.toml -p printers.pickle || goto :error

echo [5/5] Building exe...
venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name EpsonInkPadReset ^
    --paths vendor\epson_print_conf ^
    --add-data "printers.pickle;." ^
    --add-data "ui;ui" ^
    --hidden-import epson_usb_bridge ^
    --hidden-import updater ^
    --hidden-import epson_reset_gui ^
    --hidden-import pyprintlpr ^
    --collect-submodules epson_escp2 ^
    --collect-data webview ^
    --collect-submodules epson_usb ^
    --collect-all pysnmp ^
    --collect-data customtkinter ^
    --exclude-module black --exclude-module blib2to3 ^
    app_web.py || goto :error

echo.
echo Done: dist\EpsonInkPadReset.exe
exit /b 0

:error
echo.
echo Build failed.
exit /b 1
