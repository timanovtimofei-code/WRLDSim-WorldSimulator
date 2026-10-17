@echo off
rem Build WRLDSim1.exe (needs pyinstaller). data, saves and .env stay next to the exe.
rem The name WRLDSim.exe is blocked on this PC (access denied), so the build is called WRLDSim1.
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name WRLDSim1 --icon "%~dp0assets\icon.ico" --distpath . --workpath build --specpath build main.py
if exist WRLDSim1.exe echo Done: WRLDSim1.exe
