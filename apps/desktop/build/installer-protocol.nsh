; installer-protocol.nsh — register the hermes:// URL scheme for a NSIS install.
;
; electron-builder's top-level `protocols` block only reaches macOS
; (Info.plist); Windows protocol handlers come from the MSIX manifest
; extensions or, for NSIS, from these registry writes. Per-user (HKCU) so an
; unprivileged install never needs elevation.

!macro customInstall
  WriteRegStr HKCU "Software\Classes\hermes" "" "URL:${PRODUCT_NAME} Protocol"
  WriteRegStr HKCU "Software\Classes\hermes" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\hermes\DefaultIcon" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME},0"
  WriteRegStr HKCU "Software\Classes\hermes\shell" "" "open"
  WriteRegStr HKCU "Software\Classes\hermes\shell\open\command" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
!macroend

!macro customUnInstall
  DeleteRegKey HKCU "Software\Classes\hermes"
!macroend
