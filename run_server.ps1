$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:PORT = "8088"
Start-Transcript -Path "server.out.log" -Append | Out-Null
try {
  & "C:\Users\user\anaconda3\python.exe" -u "server.py"
}
finally {
  Stop-Transcript | Out-Null
}
