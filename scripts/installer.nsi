; 拾光剪影 Windows 安装器（NSIS 3.x + Modern UI 2）
; =====================================================================
; 前置：已在项目根完成 PyInstaller 打包，产物位于 dist\拾光剪影\
;         .venv312\Scripts\pyinstaller.exe app\ai_video_editor_local.spec --noconfirm
;
; 推荐：用 scripts\build_release.py 一键出包（会生成 dist\build_info.nsh，
;       把版本号、体积、有无 runtime 传进来）：
;         .venv312\Scripts\python.exe scripts\build_release.py --installer
;
; 手工编译：
;         makensis.exe scripts\installer.nsi
;
; 产物：dist\拾光剪影-Setup-<版本>.exe
;
; ⚠️ 本文件必须是 **UTF-8 with BOM**。
;    NSIS 3 在 `Unicode true` 下，遇到**无 BOM** 的脚本会按本地 ANSI(GBK)
;    解释字节流 ⇒ 所有中文字符串在安装包里都是乱码（编译不报错，装完才看见）。
;    原脚本正是无 BOM，这是本轮修的硬伤之一。改这个文件请保留 BOM。
; =====================================================================

Unicode true

; 版本号只认一个真源：app\version.py __version__。
; build_release.py 会读出它并写进 dist\build_info.nsh。
; 原来这里写死 "4.10.3"，与当时的 4.47.0 脱节 37 个次版本 ——
; 后果不只是文件名错，注册表 DisplayVersion 也会写错，
; 用户在「应用和功能」里看到的是假版本。
!if /FileExists "..\dist\build_info.nsh"
  !include "..\dist\build_info.nsh"
!endif

!ifndef APP_VERSION
  !define APP_VERSION "0.0.0"
  !warning "未找到 dist\build_info.nsh 或其中缺 APP_VERSION，产物会标成 0.0.0（版本号是假的）。建议改用 build_release.py 出包。"
!endif

!ifndef EST_SIZE_KB
  !define EST_SIZE_KB 0
!endif

!define APP_NAME      "拾光剪影"
!define APP_EXE       "拾光剪影.exe"
!define APP_PUBLISHER "拾光剪影"
; 注册表键名用 ASCII：中文键名在部分系统工具里显示为乱码，且不便脚本化
!define APP_KEY       "Software\ShiguangJianying"
!define UNINST_KEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShiguangJianying"
; SRC_DIR 相对本 .nsi 所在目录（makensis 默认 chdir 到脚本目录）
; 允许命令行 /DSRC_DIR=... 覆盖（构建脚本与冒烟测试用）
!ifndef SRC_DIR
  !define SRC_DIR     "..\dist\拾光剪影"
!endif

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"

; OUT_FILE 可被 /D 覆盖 —— 冒烟测试用它避免把假包写成正式文件名
!ifndef OUT_FILE
  !define OUT_FILE "..\dist\拾光剪影-Setup-${APP_VERSION}.exe"
!endif

Name "${APP_NAME}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${APP_KEY}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show

BrandingText "${APP_NAME} ${APP_VERSION}"

; ── 压缩 ──────────────────────────────────────────────────────────
; solid lzma 对 onedir + 几 GB 的 AI 内核非常慢（实测量级：数十分钟，
; 且吃 1~2GB 内存）。赶时间时用 /DSG_FAST_COMPRESS=1 换成 zlib。
!ifdef SG_FAST_COMPRESS
  SetCompressor /SOLID zlib
!else
  SetCompressor /SOLID lzma
!endif

; ── 界面 ──────────────────────────────────────────────────────────
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "安装 ${APP_NAME} ${APP_VERSION}"
!define MUI_WELCOMEPAGE_TEXT "即将在您的电脑上安装 ${APP_NAME}。$\r$\n$\r$\n$\r$\n本程序为本地优先的创意生产工具：图像 / 视频 / 3D / 剪辑。$\r$\n模型权重需另行从 ModelScope 等社区获取，不包含在安装包内。$\r$\n$\r$\n点击「下一步」继续。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 ${APP_NAME}"
!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ── 安装前检查 ────────────────────────────────────────────────────
Function .onInit
  ; 1) 架构：产物是 64 位（PyInstaller 在 64 位解释器下打的），32 位系统装了也跑不起来
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "本程序仅支持 64 位 Windows，当前系统为 32 位。$\r$\n$\r$\n安装已取消。"
    Abort
  ${EndIf}
  SetRegView 64

  ; 2) 已安装检测：覆盖安装会把旧文件和新文件混在一起，先告知
  ReadRegStr $0 HKLM "${UNINST_KEY}" "InstallDir"
  ${If} $0 != ""
    ReadRegStr $1 HKLM "${UNINST_KEY}" "DisplayVersion"
    ${If} $1 == ""
      StrCpy $1 "未知"
    ${EndIf}
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "检测到已安装的 ${APP_NAME}：$\r$\n$\r$\n  版本：$1$\r$\n  位置：$0$\r$\n$\r$\n继续安装将覆盖该位置的文件（用户数据不会被删除）。$\r$\n$\r$\n是否继续？" \
      IDYES +2
    Abort
  ${EndIf}

  ; 3) 结束正在运行的实例。
  ;    正在运行意味着 _internal 下的 .dll / .pyd 被加载，写入会失败 ——
  ;    而 NSIS 覆盖失败只是跳过该文件，不中断安装，用户拿到的就是
  ;    「装完打不开 / 功能缺失」的残废产物。所以必须先关。
  ;    没在运行也无妨：taskkill 返回「找不到进程」，忽略即可。
  nsExec::Exec 'taskkill /F /T /IM "${APP_EXE}"'
  Pop $0
FunctionEnd

; ── 组件 ──────────────────────────────────────────────────────────
Section "程序本体（必需）" SEC_MAIN
  SectionIn RO

  SetOutPath "$INSTDIR"
  ; 排除 runtime —— 它是可选组件，由下面单独的 Section 安装。
  ; 之所以拆开：AI 内核是整个安装包里体积最大的部分，
  ; 只用云端模型的用户没必要为它付磁盘代价。
  ; 排除项：
  ;
  ;   runtime          —— 内核是否并入由 build_info.nsh 的 HAS_RUNTIME 决定
  ;                       （体积超 2 GB 时只能单独分发，见 build_release.py 的说明）
  ;   短剧AI剪辑输出 / output / logs / debug.log
  ;                    —— **运行时产生的用户数据与日志**，绝不能打进安装包。
  ;                       实测 dist\拾光剪影 里就躺着 短剧AI剪辑输出\ 和 debug.log，
  ;                       不排除的话每装一次就给别人带一份本机测试作品。
  File /r /x "runtime" /x "短剧AI剪辑输出" /x "output" /x "logs" /x "debug.log" "${SRC_DIR}\*.*"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; 开始菜单（桌面快捷方式是可选项，见 SEC_DESKTOP）
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\uninstall.exe"

  ; 卸载入口 + 应用自身键（InstallDirRegKey 靠它记住上次装的位置）
  WriteRegStr HKLM "${APP_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${APP_KEY}" "Version" "${APP_VERSION}"

  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayName"     "${APP_NAME}"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr   HKLM "${UNINST_KEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr   HKLM "${UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr   HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr   HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  ${If} ${EST_SIZE_KB} > 0
    WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" ${EST_SIZE_KB}
  ${EndIf}
SectionEnd

; HAS_RUNTIME 由 build_release.py 生成 —— 只有当 dist\拾光剪影\runtime 存在时才定义。
; 为什么不在脚本里 IfFileExists 运行时判断：`File /r` 是**编译期**指令，
; 源目录不存在时 makensis 直接报错；而运行时判断拦不住编译期的失败。
!ifdef HAS_RUNTIME
Section "本地 AI 内核（可选，体积最大）" SEC_RUNTIME
  SetOutPath "$INSTDIR\runtime"
  File /r "${SRC_DIR}\runtime\*.*"
SectionEnd
!endif

Section "桌面快捷方式" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

; ── 语言与组件说明 ────────────────────────────────────────────────
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

LangString DESC_SEC_MAIN    ${LANG_SIMPCHINESE} "程序本体与运行库。必装，不可取消。"
LangString DESC_SEC_RUNTIME ${LANG_SIMPCHINESE} "本地推理内核（PyTorch / diffusers 等）。不装则只能使用云端模型，本地生成功能不可用。"
LangString DESC_SEC_DESKTOP ${LANG_SIMPCHINESE} "在桌面创建启动快捷方式。"

LangString DESC_SEC_MAIN    ${LANG_ENGLISH} "Application and runtime libraries. Required."
LangString DESC_SEC_RUNTIME ${LANG_ENGLISH} "Local inference runtime (PyTorch / diffusers). Skip it to use cloud models only."
LangString DESC_SEC_DESKTOP ${LANG_ENGLISH} "Create a desktop shortcut."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN}    $(DESC_SEC_MAIN)
  !ifdef HAS_RUNTIME
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_RUNTIME} $(DESC_SEC_RUNTIME)
  !endif
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} $(DESC_SEC_DESKTOP)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ── 卸载 ──────────────────────────────────────────────────────────
;
; 说清楚两件容易被误解的事，免得下次又有人「修」错方向：
;
; ① 卸载器**不需要**把自己复制到临时目录。
;    这是 NSIS 内建行为：uninstaller 启动时自动复制到 $TEMP 再从那里运行，
;    所以 RMDir /r "$INSTDIR" 不会卡在「删不掉正在运行的自己」上。
;    （只有显式传 `_?=` 参数才会关闭这个自复制行为。）
;    真正需要处理的是**当前工作目录**：若 CWD 还在 $INSTDIR，
;    目录被占用会导致删除失败，所以下面先 SetOutPath $TEMP。
;
; ② 绝对不能无条件 RMDir /r "$INSTDIR"。
;    这个程序会把用户作品写在自己目录下（实测 dist\拾光剪影\短剧AI剪辑输出、
;    output\、素材库\ 等）。原脚本整目录删 ⇒ **卸载等于删光用户作品**，
;    而且没有任何提示。所以这里必须先问，并且「保留」分支只删程序文件。
Section "Uninstall"
  ; 先关程序，否则 _internal 下的文件被占用、删不掉
  nsExec::Exec 'taskkill /F /T /IM "${APP_EXE}"'
  Pop $0

  SetOutPath "$TEMP"

  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"

  MessageBox MB_YESNO|MB_ICONEXCLAMATION \
    "是否同时删除安装目录下的用户数据？$\r$\n$\r$\n包括：作品输出、素材库、项目文件、日志与配置。$\r$\n位置：$INSTDIR$\r$\n$\r$\n选择「否」将保留这些文件（推荐，便于重装后继续使用）。" \
    IDYES sg_wipe_all IDNO sg_keep_data

  sg_wipe_all:
    RMDir /r "$INSTDIR"
    Goto sg_registry

  sg_keep_data:
    ; 只删程序本体；用户数据目录原样留着
    RMDir /r "$INSTDIR\_internal"
    RMDir /r "$INSTDIR\runtime"
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$INSTDIR\*.dll"
    Delete "$INSTDIR\*.log"
    ; 不带 /r：目录非空时自动失败，正好保住数据
    RMDir "$INSTDIR"

  sg_registry:
    DeleteRegKey HKLM "${UNINST_KEY}"
    DeleteRegKey HKLM "${APP_KEY}"
SectionEnd
