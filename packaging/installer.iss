#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
[Setup]
AppId={{0D3C6F2E-92A2-4EE8-B052-3A96B1425E8A}
AppName=Omni PDF
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\OmniPDF
DefaultGroupName=Omni PDF
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=OmniPDF-Setup-{#AppVersion}-windows-x64
SetupIconFile=..\build\release-inputs\omni.ico
LicenseFile=..\LICENSE
AppMutex=OmniPDF.App
CloseApplications=no
RestartApplications=no
Compression=lzma2
SolidCompression=yes

[Files]
Source: "..\dist\OmniPDF.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\release-inputs\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Omni PDF"; Filename: "{app}\OmniPDF.exe"

[Run]
Filename: "{app}\OmniPDF.exe"; Description: "Launch Omni PDF"; Flags: nowait postinstall skipifsilent; Check: not IsUpdate
Filename: "{app}\OmniPDF.exe"; Flags: nowait; Check: IsUpdate

[Code]
function OpenProcess(dwDesiredAccess: Cardinal; bInheritHandle: Boolean; dwProcessId: Cardinal): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(hHandle: THandle; dwMilliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function GetLastError: Cardinal;
  external 'GetLastError@kernel32.dll stdcall';

function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:OMNIPDFUPDATE|0}') = '1';
end;

function InitializeSetup: Boolean;
var
  Pid: Integer;
  ProcessHandle: THandle;
  WaitResult: Cardinal;
begin
  Result := True;
  if not IsUpdate then exit;
  Pid := StrToIntDef(ExpandConstant('{param:OMNIPDFWAITPID|0}'), 0);
  if Pid <= 0 then begin Result := False; exit; end;
  ProcessHandle := OpenProcess($00100000, False, Pid);
  if ProcessHandle = 0 then begin
    { A process that has already exited is safe only if the mutex is also gone. }
    Result := (GetLastError = 87) and not CheckForMutexes('OmniPDF.App');
    exit;
  end;
  WaitResult := WaitForSingleObject(ProcessHandle, 30000);
  CloseHandle(ProcessHandle);
  Result := WaitResult = 0;
end;
