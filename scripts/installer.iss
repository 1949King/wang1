; 拾光剪影完整 Windows 安装器（Inno Setup 6.5+）
; 由 scripts/build_release.py 注入版本、源码目录与输出目录。
#ifndef APP_VERSION
  #error APP_VERSION must be supplied by build_release.py
#endif
#ifndef SRC_DIR
  #error SRC_DIR must be supplied by build_release.py
#endif
#ifndef OUT_DIR
  #error OUT_DIR must be supplied by build_release.py
#endif
#ifndef ROOT_DIR
  #error ROOT_DIR must be supplied by build_release.py
#endif
#ifndef DISK_SPANNING
  #define DISK_SPANNING "no"
#endif
; Lite 轻量版开关：由 build_release.py --lite 注入 /DLITE_BUILD。
; 缺省（未定义 LITE_BUILD）= 全量版，产物名无后缀，行为与原来完全一致。
#ifdef LITE_BUILD
  #define SG_OUTPUT_SUFFIX "-Lite"
#else
  #define SG_OUTPUT_SUFFIX ""
#endif

[Setup]
AppId={{7A1D0B3E-7C6C-4F4E-9F0A-5E7C0E8B3F21}
AppName=拾光剪影
AppVersion={#APP_VERSION}
AppPublisher=拾光剪影
DefaultDirName={autopf64}\拾光剪影
DefaultGroupName=拾光剪影
OutputDir={#OUT_DIR}
OutputBaseFilename=拾光剪影-Setup-{#APP_VERSION}{#SG_OUTPUT_SUFFIX}
LicenseFile={#ROOT_DIR}\LICENSE.txt
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\拾光剪影.exe
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
DiskSpanning={#DISK_SPANNING}
; 本机实测超过 2 GiB 的单文件或数据分卷会在初始化阶段退出；固定 1 GiB 分片。
DiskSliceSize=1073741824
WizardStyle=modern

[Languages]
; 简体中文向导（2026-11-21）：缺 [Languages] 段时 Inno 默认用内置英文，
; 向导全是 Next/Cancel/Install（编译不报错、装完才发现）。语言文件随仓库
; 携带（官方 6.5.0+ 翻译），不依赖出包机 Inno 目录是否带该翻译；
; 只配一种语言时不弹语言选择框，卸载器同样跟随中文。
Name: "chinesesimplified"; MessagesFile: "{#ROOT_DIR}\scripts\ChineseSimplified.isl"

[Files]
#ifndef LITE_BUILD
Source: "{#SRC_DIR}\*"; DestDir: "{app}"; Excludes: "短剧AI剪辑输出\*,output\*,logs\*,debug.log"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
; Lite 版：额外排除 runtime\*（AI 内核不随包），四项私有排除与全量一致。
; 全量行必须排在 Lite 行之前 —— 契约测试取第一条排除行断言「不含内核」。
; 🔴 Lite 行禁止 createallsubdirs（2026-11-20 实测）：该标志会为被排除的
; runtime\* 照样建出**空目录**，而 runtime_pack.ensure_runtime_path() 只判
; isdir ⇒ 空目录被误判「内核已就位」，Lite 假报 AI 可用。去掉后 Inno 只按
; 实际文件建目录，装完 runtime 不存在，诚实降级路径才成立。
Source: "{#SRC_DIR}\*"; DestDir: "{app}"; Excludes: "短剧AI剪辑输出\*,output\*,logs\*,debug.log,runtime\*"; Flags: ignoreversion recursesubdirs
#endif

#ifdef LITE_BUILD
[InstallDelete]
; 全量 → Lite 属同一 AppId 原地降级：清掉旧内核残骸（约 4.37 GB），不碰用户数据。
Type: filesandordirs; Name: "{app}\runtime"
#endif

[Icons]
Name: "{group}\拾光剪影"; Filename: "{app}\拾光剪影.exe"
Name: "{group}\卸载 拾光剪影"; Filename: "{uninstallexe}"
Name: "{autodesktop}\拾光剪影"; Filename: "{app}\拾光剪影.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Run]
Filename: "{app}\拾光剪影.exe"; Description: "立即启动 拾光剪影"; Flags: nowait postinstall skipifsilent unchecked

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { 默认卸载只删已安装文件。静默卸载不询问，始终保留后产生的用户数据。 }
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox('是否同时删除安装目录下的用户数据？' + #13#10 +
              '选择“否”将保留作品输出、素材库和项目文件。',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{app}\短剧AI剪辑输出'), True, True, True);
      DelTree(ExpandConstant('{app}\output'), True, True, True);
      DelTree(ExpandConstant('{app}\素材库'), True, True, True);
    end;
end;
