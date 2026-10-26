; Copyright 2026 stickleetoto
; SPDX-License-Identifier: Apache-2.0
;
; Per-user Inno Setup script for BIO Community Edition. Compile through
; packaging\build_windows.ps1, which defines the values checked below.
; Installs to %LOCALAPPDATA%\Programs\BIO-CE without administrator rights.
; Personal data under %LOCALAPPDATA%\BIO-CE is never installed, replaced, or
; removed by Setup; uninstall removes it only after an explicit opt-in prompt.

#ifndef AppVersion
  #error Define AppVersion (for example 0.2.0-rc1).
#endif
#ifndef NumericVersion
  #error Define NumericVersion (for example 0.2.0.1).
#endif
#ifndef PayloadDir
  #error Define PayloadDir (the assembled GUI + MCP payload folder).
#endif
#ifndef OutputDir
  #error Define OutputDir.
#endif
#ifndef IconFile
  #error Define IconFile.
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "BIO-CE-Setup-v" + AppVersion
#endif

[Setup]
AppId={{8A3FE668-FA42-4564-9D91-AC3121E700EA}
AppName=BIO Community Edition
AppVersion={#AppVersion}
AppVerName=BIO Community Edition {#AppVersion}
AppPublisher=stickleetoto
AppCopyright=Copyright 2026 stickleetoto. Apache-2.0.
DefaultDirName={userpf}\BIO-CE
DefaultGroupName=BIO CE
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
DirExistsWarning=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\BIO-CE.exe
UninstallDisplayName=BIO Community Edition
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
CloseApplications=yes
; Must match bio_ce.desktop.INSTANCE_MUTEX_NAME.
AppMutex=BIO-CE-Desktop-SingleInstance
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#NumericVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCompany=stickleetoto
VersionInfoDescription=BIO Community Edition Setup
VersionInfoCopyright=Copyright 2026 stickleetoto. Apache-2.0.
VersionInfoProductName=BIO Community Edition

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
english.ConfirmUninstall=Remove %1 from this Windows user?%n%nYour memories, settings, and backups in your AppData\Local\BIO-CE folder are kept unless you choose to remove them in the next step. Disconnect Codex or Claude on the BIO CE Connections page first; uninstall does not edit host MCP settings.
korean.ConfirmUninstall=이 Windows 사용자에서 %1을(를) 제거할까요?%n%nAppData\Local\BIO-CE 폴더의 기억, 설정, 백업은 다음 단계에서 삭제를 직접 선택하지 않는 한 보존됩니다. Codex 또는 Claude 연결은 먼저 BIO CE의 Connections 화면에서 해제하세요. 제거 프로그램은 호스트 MCP 설정을 수정하지 않습니다.

[CustomMessages]
english.LaunchApp=Start BIO CE
english.RemoveDataPrompt=Also remove BIO CE local data (memories, settings, and MCP configuration backups)?%n%n%1%n%nThis is not a secure erase and cannot be undone. Choose No to keep your data.
english.RemoveDataFailed=Some BIO CE data could not be removed because it is in use. Close any AI host that uses BIO CE and delete this folder manually:%n%n%1
english.DataDirRefused=Choose a program folder outside the BIO CE data folder:%n%n%1
korean.LaunchApp=BIO CE 시작
korean.RemoveDataPrompt=BIO CE 로컬 데이터(기억, 설정, MCP 설정 백업)도 삭제할까요?%n%n%1%n%n안전 삭제가 아니며 되돌릴 수 없습니다. 데이터를 보존하려면 [아니요]를 선택하세요.
korean.RemoveDataFailed=사용 중인 파일이 있어 일부 BIO CE 데이터를 삭제하지 못했습니다. BIO CE를 사용하는 AI 호스트를 종료한 뒤 다음 폴더를 직접 삭제하세요:%n%n%1
korean.DataDirRefused=BIO CE 데이터 폴더 밖의 프로그램 폴더를 선택하세요:%n%n%1

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Replace the frozen runtimes wholesale so no stale DLL from an older build remains.
Type: filesandordirs; Name: "{app}\_internal"; Check: IsBioCeInstallDir
Type: filesandordirs; Name: "{app}\MCP\_internal"; Check: IsBioCeInstallDir
; Files left by the unreleased v0.2.0 IExpress developer preview.
Type: files; Name: "{app}\uninstall.ps1"; Check: IsBioCeInstallDir

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\BIO CE\BIO CE"; Filename: "{app}\BIO-CE.exe"; WorkingDir: "{app}"; Comment: "Local BIO CE memory manager"
Name: "{autodesktop}\BIO CE"; Filename: "{app}\BIO-CE.exe"; WorkingDir: "{app}"; Comment: "Local BIO CE memory manager"; Tasks: desktopicon

[Registry]
; Remove the uninstall entry written by the unreleased IExpress developer preview.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\BIO-CE"; ValueType: none; Flags: deletekey dontcreatekey

[Run]
Filename: "{app}\BIO-CE.exe"; Description: "{cm:LaunchApp}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
function DataRoot(): String;
begin
  Result := ExpandConstant('{localappdata}\BIO-CE');
end;

function IsBioCeInstallDir(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\BIO-CE.exe'));
end;

function IsSameOrInside(const Path, Root: String): Boolean;
var
  P, R: String;
begin
  P := Lowercase(AddBackslash(ExpandFileName(Path)));
  R := Lowercase(AddBackslash(ExpandFileName(Root)));
  Result := Copy(P, 1, Length(R)) = R;
end;

function OverlapsDataRoot(const Dir: String): Boolean;
begin
  Result := IsSameOrInside(Dir, DataRoot()) or IsSameOrInside(DataRoot(), Dir);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and OverlapsDataRoot(WizardDirValue()) then
  begin
    MsgBox(FmtMessage(CustomMessage('DataDirRefused'), [DataRoot()]), mbError, MB_OK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if OverlapsDataRoot(ExpandConstant('{app}')) then
    Result := FmtMessage(CustomMessage('DataDirRefused'), [DataRoot()]);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) and DirExists(DataRoot()) then
  begin
    if MsgBox(FmtMessage(CustomMessage('RemoveDataPrompt'), [DataRoot()]),
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      if not DelTree(DataRoot(), True, True, True) or DirExists(DataRoot()) then
        MsgBox(FmtMessage(CustomMessage('RemoveDataFailed'), [DataRoot()]), mbError, MB_OK);
    end;
  end;
end;
