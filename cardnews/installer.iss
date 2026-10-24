; 민주의 카드뉴스 제작 프로그램 설치 파일 (Inno Setup 6). GitHub Actions가 dist\MinjuCardNews.exe로 dist\MinjuCardNews-Setup.exe를 만든다.
; 관리자 권한 없이 내 계정(%LOCALAPPDATA%\Programs)에 깔고, 바탕화면·시작 메뉴 바로가기와 '앱 및 기능'의 제거를 만든다.
; 키·카드뉴스(문서\민주의 카드뉴스 제작 프로그램)는 지우거나 다시 깔아도 그대로 남는다.
#define AppName "민주의 카드뉴스"
#ifndef AppVer
  #define AppVer "1.0"
#endif

[Setup]
AppId={{6E0F3B2A-6C1D-4E8B-9A57-50B0C4A1D9E1}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName}
AppPublisher=SOBORU
DefaultDirName={localappdata}\Programs\MinjuCardNews
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=MinjuCardNews-Setup
SetupIconFile=static\app-icon.ico
UninstallDisplayIcon={app}\MinjuCardNews.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=force

[Languages]
#if FileExists(CompilerPath + "Languages\Korean.isl")
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
#else
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Files]
Source: "dist\MinjuCardNews.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\MinjuCardNews.exe"; WorkingDir: "{app}"
Name: "{userprograms}\{#AppName}"; Filename: "{app}\MinjuCardNews.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\MinjuCardNews.exe"; Description: "{#AppName} 바로 켜기"; Flags: nowait postinstall skipifsilent

[Code]
// 켜져 있으면 끄고 깐다 (예전 버전이 뒤에서 돌고 있으면 파일을 못 바꿈)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM MinjuCardNews.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

function InitializeUninstall(): Boolean;
var Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM MinjuCardNews.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := True;
end;
