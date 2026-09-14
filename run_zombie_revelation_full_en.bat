@echo off
chcp 65001 >nul
title Recap Comics - Zombie Revelation: 82-08 (Episodes 1-120 English OmniVoice)
cd /d "%~dp0"
echo ===============================================================================
echo   Recap Comics: Zombie Revelation: 82-08 (Episodes 1-120 Full Series)
echo   Language: English (US)
echo   TTS Voice: OmniVoice Andrew Clone (clone_andrew)
echo   VLM Model: Gemini 3.8 Flash (Auto Profile Rotation)
echo ===============================================================================
.venv\Scripts\python.exe run_zombie_revelation_82_08_full_en.py
pause
