; 拾光剪影 Windows 安装器 (NSIS 3.x)
; =====================================================================
; 前置: 已在项目根目录完成 PyInstaller 打包, 产物位于 dist\拾光剪影\
;         .venv312\Scripts\pyinstaller.exe app\ai_video_editor_local.spec --noconfirm
; 用法: makensis.exe scripts\installer.nsi
; 产物: dist\拾光剪影-Setup-4.10.3.exe
; =====================================================================

!define APP_NAME "拾光剪影"
!define APP_EXE "拾光剪影.exe"
!define APP_VERSION "4.10.3"
!define APP_PUBLISHER "拾光剪影"
; SRC_DIR 相对本 .nsi 所在目录 (scripts\), 指向项目根 dist 下的 onedir 产物
!define SRC_DIR "..\dist\拾光剪影"

Unicode true
SetCompressor /SOLID lzma

Name "${APP_NAME}"
OutFile "..\dist\拾光剪影-Setup-${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${SRC_DIR}\*.*"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; 安装信息注册（卸载入口）
  WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""

  ; 开始菜单 + 桌面快捷方式
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKLM "Software\${APP_NAME}"
SectionEnd