; Included by the NSIS installer of electron-builder (electron-builder.yml).

!macro customUnInstall
  ; "Launch at login" of the tray menu: Electron writes the entry under the
  ; AppUserModelID of the application (src/autostart.ts). An update keeps it.
  ${ifNot} ${isUpdated}
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP_ID}"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "${APP_ID}"
  ${endIf}
!macroend
