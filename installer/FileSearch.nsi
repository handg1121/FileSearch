; Build with tools/build_installer.py. All files are embedded; installation is offline.
Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
SetDatablockOptimize on
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef APP_VERSION
  !error "APP_VERSION is required"
!endif
!ifndef BUNDLE
  !error "BUNDLE is required"
!endif
!ifndef OUTPUT_EXE
  !error "OUTPUT_EXE is required"
!endif
!define APP_ID "handg1121.FileSearch"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\FileSearch"
Name "FileSearch ${APP_VERSION}"
OutFile "${OUTPUT_EXE}"
InstallDir "$LOCALAPPDATA\Programs\FileSearch"
BrandingText "FileSearch"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1042 "ProductName" "FileSearch"
VIAddVersionKey /LANG=1042 "FileDescription" "FileSearch 설치 프로그램"
VIAddVersionKey /LANG=1042 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1042 "LegalCopyright" "FileSearch contributors"
ShowInstDetails show
ShowUninstDetails show
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "FileSearch 설치"
!define MUI_WELCOMEPAGE_TEXT "파일을 검색하고 태그로 정리하는 프로그램을 설치해요.$\r$\n$\r$\n현재 사용자 계정에 설치하며, 기존 파일과 태그·설정은 그대로 유지돼요. 설치 전에 실행 중인 FileSearch를 닫아 주세요."
!define MUI_FINISHPAGE_RUN "$INSTDIR\FileSearch.exe"
!define MUI_FINISHPAGE_RUN_TEXT "FileSearch 실행"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Korean"

Var RunningLock
Var AppLock
Var SetupMutex

; The launcher uses byte 0 in these same files. Hold both locks while copying/deleting.
!macro LockFunctions PREFIX
Function ${PREFIX}ReleaseLocks
  ${If} $AppLock != 0
  ${AndIf} $AppLock != -1
    System::Call 'kernel32::UnlockFile(p $AppLock, i 0, i 0, i 1, i 0)'
    System::Call 'kernel32::CloseHandle(p $AppLock)'
  ${EndIf}
  ${If} $RunningLock != 0
  ${AndIf} $RunningLock != -1
    System::Call 'kernel32::UnlockFile(p $RunningLock, i 0, i 0, i 1, i 0)'
    System::Call 'kernel32::CloseHandle(p $RunningLock)'
  ${EndIf}
  StrCpy $RunningLock 0
  StrCpy $AppLock 0
FunctionEnd

Function ${PREFIX}AcquireLocks
  StrCpy $RunningLock 0
  StrCpy $AppLock 0
  ClearErrors
  CreateDirectory "$INSTDIR\.updates"
  IfErrors locked
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\.updates\running.lock", i 0xC0000000, i 7, p 0, i 4, i 0x80, p 0) p .r0'
  StrCpy $RunningLock $0
  ${If} $RunningLock == -1
    Goto locked
  ${EndIf}
  System::Call 'kernel32::LockFile(p $RunningLock, i 0, i 0, i 1, i 0) i .r0'
  ${If} $0 == 0
    Goto locked
  ${EndIf}
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\.updates\app.lock", i 0xC0000000, i 7, p 0, i 4, i 0x80, p 0) p .r0'
  StrCpy $AppLock $0
  ${If} $AppLock == -1
    Goto locked
  ${EndIf}
  System::Call 'kernel32::LockFile(p $AppLock, i 0, i 0, i 1, i 0) i .r0'
  ${If} $0 == 0
    Goto locked
  ${EndIf}
  Return
locked:
  Call ${PREFIX}ReleaseLocks
  MessageBox MB_OK|MB_ICONEXCLAMATION "프로그램이 실행 중이거나 설치 폴더에 쓸 수 없어요. FileSearch를 완전히 닫은 뒤 다시 시도해 주세요." /SD IDOK
  SetErrorLevel 1
  Abort
FunctionEnd

Function ${PREFIX}CheckPaths
  ; Install/uninstall only in our fixed per-user directory. Reject redirected roots.
  ${If} $INSTDIR != "$LOCALAPPDATA\Programs\FileSearch"
    Goto unsafe_path
  ${EndIf}
  System::Call 'kernel32::GetFileAttributesW(w "$INSTDIR") i .r0'
  ${If} $0 != -1
    IntOp $0 $0 & 0x400
    ${If} $0 != 0
      Goto unsafe_path
    ${EndIf}
  ${EndIf}
  System::Call 'kernel32::GetFileAttributesW(w "$INSTDIR\versions") i .r0'
  ${If} $0 != -1
    IntOp $0 $0 & 0x400
    ${If} $0 != 0
      Goto unsafe_path
    ${EndIf}
  ${EndIf}
  System::Call 'kernel32::GetFileAttributesW(w "$INSTDIR\.updates") i .r0'
  ${If} $0 != -1
    IntOp $0 $0 & 0x400
    ${If} $0 != 0
      Goto unsafe_path
    ${EndIf}
  ${EndIf}
  Return
unsafe_path:
  MessageBox MB_OK|MB_ICONSTOP "설치 경로가 올바르지 않아요. 기본 설치 폴더를 확인해 주세요." /SD IDOK
  SetErrorLevel 1
  Abort
FunctionEnd
!macroend
!insertmacro LockFunctions ""
!insertmacro LockFunctions "un."

Function .onInit
  SetShellVarContext current
  SetRegView 64
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\FileSearch"
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "64비트 Windows가 필요해요." /SD IDOK
    Quit
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Windows 10 이상이 필요해요." /SD IDOK
    Quit
  ${EndIf}
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\FileSearch.Setup") p .r0 ?e'
  Pop $1
  StrCpy $SetupMutex $0
  ${If} $1 == 183
    MessageBox MB_OK|MB_ICONEXCLAMATION "다른 FileSearch 설치 프로그램이 실행 중이에요." /SD IDOK
    Quit
  ${EndIf}
  Call CheckPaths
  ReadINIStr $0 "$INSTDIR\installation.ini" "FileSearch" "Id"
  ${If} $0 != "${APP_ID}"
    IfFileExists "$INSTDIR\FileSearch.exe" existing_unknown
    IfFileExists "$INSTDIR\versions\*.*" existing_unknown
  ${EndIf}
  Return
existing_unknown:
  MessageBox MB_OK|MB_ICONSTOP "기본 설치 폴더에 다른 설치본이 있어요. 해당 폴더를 다른 위치에 보관한 뒤 다시 설치해 주세요." /SD IDOK
  Quit
FunctionEnd

Section "FileSearch" SEC_APP
  Call CheckPaths
  Call AcquireLocks
  SetOutPath "$INSTDIR"
  WriteINIStr "$INSTDIR\installation.ini" "FileSearch" "Id" "${APP_ID}"
  SetOverwrite on
  ClearErrors
  File /r "${BUNDLE}\*"
  IfErrors copy_failed
  Call ReleaseLocks
  ; Registration updates only installation state, and does not open the app or read user data.
  ClearErrors
  ExecWait '"$INSTDIR\FileSearch.exe" --register-install' $0
  IfErrors register_failed
  ${If} $0 != 0
    Goto register_failed
  ${EndIf}
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  IfErrors copy_failed
  CreateShortcut "$SMPROGRAMS\FileSearch.lnk" "$INSTDIR\FileSearch.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "FileSearch"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "FileSearch"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\FileSearch.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "URLInfoAbout" "https://github.com/handg1121/FileSearch"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  Goto complete
register_failed:
  MessageBox MB_OK|MB_ICONSTOP "설치를 완료하지 못했어요. FileSearch를 닫고 설치 프로그램을 다시 실행해 주세요." /SD IDOK
  SetErrorLevel 1
  Abort
copy_failed:
  Call ReleaseLocks
  SetErrorLevel 1
  Abort "설치 파일을 복사하지 못했어요. 다시 시도해 주세요."
complete:
SectionEnd

Function .onGUIEnd
  Call ReleaseLocks
  ${If} $SetupMutex != 0
    System::Call 'kernel32::CloseHandle(p $SetupMutex)'
  ${EndIf}
FunctionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  Call un.CheckPaths
  ReadINIStr $0 "$INSTDIR\installation.ini" "FileSearch" "Id"
  ${If} $0 != "${APP_ID}"
    MessageBox MB_OK|MB_ICONSTOP "FileSearch 설치 폴더를 확인할 수 없어요." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  Call un.CheckPaths
  Call un.AcquireLocks
  SetOutPath "$TEMP"
  ; Only installer-owned program folders. %APPDATA%\FileSearch and collected files stay intact.
  ClearErrors
  Delete "$INSTDIR\FileSearch.exe"
  RMDir /r "$INSTDIR\versions"
  IfErrors uninstall_failed
  Call un.ReleaseLocks
  RMDir /r "$INSTDIR\.updates"
  Delete "$INSTDIR\시작 안내.txt"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.txt"
  Delete "$INSTDIR\licenses\NSIS-LICENSE.txt"
  RMDir "$INSTDIR\licenses"
  Delete "$INSTDIR\installation.ini"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$SMPROGRAMS\FileSearch.lnk"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  RMDir "$INSTDIR"
  Goto uninstall_complete
uninstall_failed:
  Call un.ReleaseLocks
  SetErrorLevel 1
  Abort "일부 프로그램 파일을 지우지 못했어요. 잠시 뒤 다시 제거해 주세요."
uninstall_complete:
SectionEnd

Function un.onGUIEnd
  Call un.ReleaseLocks
FunctionEnd
