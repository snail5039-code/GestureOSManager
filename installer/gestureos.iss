#define MyAppName "GestureOSManager"
#define MyAppVersion "1.0.0"
#define MyPublisher "snail5039"
#define MyExeName "GestureOSAgent.exe"

; ✅ 너 환경에 맞게 여기 2개만 경로 수정하면 됨
#define AgentDir "D:\puh\GestureOSManager\GestureOSManager\release\agent"
#define ManagerJar "D:\puh\GestureOSManager\GestureOSManager\gestureosManager\target\gestureosManager-0.0.1-SNAPSHOT.jar"

[Setup]
AppId={{B2D4C2A9-6B9C-4B8A-9C68-6D1B66B8F001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyPublisher}
DefaultDirName={pf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=D:\puh\GestureOSManager\GestureOSManager\dist-installer
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
; Agent onedir 전체
Source: "{#AgentDir}\*"; DestDir: "{app}\agent"; Flags: recursesubdirs ignoreversion

; Manager jar
Source: "{#ManagerJar}"; DestDir: "{app}\server"; DestName: "manager.jar"; Flags: ignoreversion

; 실행 배치(설치 시 생성)
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  BatPath: String;
  BatContent: String;
begin
  if CurStep = ssInstall then
  begin
    BatPath := ExpandConstant('{app}\start-manager.bat');
    BatContent :=
      '@echo off' + #13#10 +
      'cd /d "%~dp0"' + #13#10 +
      'echo Starting Manager (8080)...' + #13#10 +
      'java -jar "%~dp0server\manager.jar"' + #13#10;
    SaveStringToFile(BatPath, BatContent, False);
  end;
end;

[Icons]
Name: "{group}\Start Agent";   Filename: "{app}\agent\{#MyExeName}"
Name: "{group}\Start Manager"; Filename: "{app}\start-manager.bat"
Name: "{group}\Uninstall";     Filename: "{uninstallexe}"

[Run]
; 설치 끝나면 에이전트 바로 실행(원하면 주석처리)
Filename: "{app}\agent\{#MyExeName}"; Description: "Run Agent"; Flags: nowait postinstall skipifsilent
