# Genera un video de prueba con voz sintética en inglés sobre un fondo con reloj.
#   powershell -File tools/make_sample.ps1                          → samples/demo.mp4
#   powershell -File tools/make_sample.ps1 -Script tools/samples/dialogue.txt -Out samples/dialogue.mp4
# Guion: una línea por intervención "Voz|texto" (Voz = parte del nombre, p. ej. Zira, George);
# las líneas vacías agregan una pausa.
param(
  [string]$Script = "$PSScriptRoot\samples\demo.txt",
  [string]$Out = "$PSScriptRoot\..\samples\demo.mp4"
)

$ErrorActionPreference = "Stop"
$dir = Split-Path $Out
New-Item -ItemType Directory -Force $dir | Out-Null
$wav = Join-Path $dir ("_speech_" + [IO.Path]::GetFileNameWithoutExtension($Out) + ".wav")

Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Culture.Name -like "en-*" }
$s.SetOutputToWaveFile($wav)
$pb = New-Object System.Speech.Synthesis.PromptBuilder
foreach ($line in Get-Content $Script -Encoding UTF8) {
  if ($line.Trim() -eq "") { $pb.AppendBreak([TimeSpan]::FromMilliseconds(900)); continue }
  $who, $text = $line -split "\|", 2
  if (-not $text) { $text = $who; $who = "" }
  $v = $voices | Where-Object { $_.Name -like "*$who*" } | Select-Object -First 1
  if (-not $v) { $v = $voices | Select-Object -First 1 }
  $pb.StartVoice($v)
  $pb.AppendText($text.Trim())
  $pb.EndVoice()
  $pb.AppendBreak([TimeSpan]::FromMilliseconds(350))
}
$s.Speak($pb)
$s.Dispose()

ffmpeg -y -loglevel error -f lavfi -i "color=c=0xF4F1EA:s=1280x720:r=25" -i $wav `
  -vf "drawtext=fontfile='C\:/Windows/Fonts/arial.ttf':text='%{pts\:hms}':fontsize=96:fontcolor=0x111111:x=(w-tw)/2:y=(h-th)/2" `
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 128k $Out
if ($LASTEXITCODE -ne 0) { throw "ffmpeg falló ($LASTEXITCODE)" }
Remove-Item $wav
Write-Output "OK: $Out"
