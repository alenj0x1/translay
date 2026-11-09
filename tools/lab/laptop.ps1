<#
Lab de CPU y gráfica integrada de Translay, para correr una vez en otro equipo.

Usa el Python, el código y los modelos que ya instaló la app de escritorio de Translay; baja whisper.cpp con
Vulkan (la gráfica integrada AMD o Intel) y una muestra de 71 s desde la pre-release del lab, mide cada
variante (tools/lab/cpu.py) y deja en el Escritorio un translay-lab-<fecha>.json para enviar de vuelta.
No pide administrador, no instala nada en el sistema y borra lo que bajó al terminar (salvo -Keep).

    powershell -ExecutionPolicy Bypass -File laptop.ps1            (todo: ~25 min, baja hasta ~2,6 GB)
    powershell -ExecutionPolicy Bypass -File laptop.ps1 -Quick     (sin el modelo grande: ~10 min, ~1 GB)
#>
param(
    [string]$Tag = "lab-cpu-1",
    [switch]$Quick,
    [switch]$Keep,
    [int]$Rounds = 2,
    # para probar el script sin la app instalada o sin la pre-release: rutas propias y una carpeta con los archivos
    [string]$Python = "",
    [string]$Code = "",
    [string]$Assets = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # la barra de Invoke-WebRequest de PowerShell 5 lo hace 10 veces más lento
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$desk = [Environment]::GetFolderPath("Desktop")
$log = Join-Path $desk "translay-lab-$stamp.log"
$work = Join-Path $env:TEMP "translay-lab"
function Say($msg) { $line = "$(Get-Date -Format HH:mm:ss)  $msg"; Write-Host $line; Add-Content -Path $log -Value $line -Encoding UTF8 }
function Fail($msg) { Say "ERROR: $msg"; Say "No se midió nada. Envía este archivo: $log"; exit 1 }

Say "Lab de CPU y gráfica integrada de Translay ($Tag)"

# ------------------------------------------------------------------ revisar antes de empezar
$appData = Join-Path $env:LOCALAPPDATA "dev.alejandro.translay"
$python = if ($Python) { $Python } else { Join-Path $appData "runtime\server\Scripts\python.exe" }
if (-not (Test-Path $python)) { Fail "no encontré Translay instalado (falta $python). Instala la app y ábrela una vez." }

$install = if ($Code) { Split-Path $Code -Parent } else { $null }
if (-not $install) { foreach ($root in "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
                  "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall") {
    if (-not (Test-Path $root)) { continue }
    $k = Get-ChildItem $root | Get-ItemProperty | Where-Object { $_.DisplayName -eq "Translay" } | Select-Object -First 1
    if ($k -and $k.InstallLocation) { $install = $k.InstallLocation.Trim('"'); break }
} }
if (-not $install) {
    $install = @("$env:LOCALAPPDATA\Translay", "$env:LOCALAPPDATA\Programs\Translay", "$env:ProgramFiles\Translay") |
        Where-Object { Test-Path (Join-Path $_ "translay\vt\__init__.py") } | Select-Object -First 1
}
$appCode = if ($Code) { $Code } elseif ($install) { Join-Path $install "translay" } else { "" }
if (-not $appCode -or -not (Test-Path (Join-Path $appCode "vt\__init__.py"))) { Fail "no encontré la carpeta del programa Translay." }
$tools = Join-Path $install "tools"
Say "Translay: $install"

if (Get-Process -Name translay -ErrorAction SilentlyContinue) {
    Fail "Translay está abierto: ciérralo (también desde el ícono junto al reloj) y vuelve a correr el lab, así no compite por la CPU."
}

$os = Get-CimInstance Win32_OperatingSystem
$freeRamGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:TEMP.Substring(0,2))'"
$freeDiskGb = [math]::Round($disk.FreeSpace / 1GB, 1)
if ($freeRamGb -lt 2.5) { Fail "hay $freeRamGb GB de RAM libre; cierra programas hasta tener al menos 2,5 GB." }
if ($freeDiskGb -lt 4) { Fail "hay $freeDiskGb GB libres en $($env:TEMP.Substring(0,2)); hacen falta 4 GB." }

# ------------------------------------------------------------------ el equipo
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
    @{ name = $_.Name; driver = $_.DriverVersion; driver_date = "$($_.DriverDate)"; vram_mb = [math]::Round($_.AdapterRAM / 1MB) } })
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
$plan = (powercfg /getactivescheme) -replace '.*\((.*)\).*', '$1'
$hw = [ordered]@{
    cpu = $cpu.Name.Trim(); cores = $cpu.NumberOfCores; threads = $cpu.NumberOfLogicalProcessors; max_mhz = $cpu.MaxClockSpeed
    ram_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1); free_ram_gb = $freeRamGb
    gpus = $gpus; vulkan = (Test-Path "$env:WINDIR\System32\vulkan-1.dll")
    on_battery = [bool]($battery -and $battery.BatteryStatus -eq 1); power_plan = "$plan"
    windows = "$($os.Caption) $($os.Version)"
}
Say "Equipo: $($hw.cpu) · $($hw.cores) núcleos / $($hw.threads) hilos · $($hw.ram_gb) GB · $(($gpus | ForEach-Object { $_.name }) -join ', ')"
if ($hw.on_battery) { Say "Aviso: está con batería; conéctalo al cargador para medir con toda la potencia." }

# ------------------------------------------------------------------ bajar lo del lab
New-Item -ItemType Directory -Force -Path $work | Out-Null
function Get-File($url, $dest) {
    if (Test-Path $dest) { return }
    $local = if ($Assets) { Join-Path $Assets (Split-Path $dest -Leaf) } else { "" }
    if ($local -and (Test-Path $local)) { Copy-Item $local $dest; return }
    Say "Bajando $(Split-Path $dest -Leaf)…"
    try { Invoke-WebRequest -Uri $url -OutFile "$dest.part" -UseBasicParsing -TimeoutSec 60 }
    catch { Remove-Item "$dest.part" -ErrorAction SilentlyContinue; Fail "no se pudo bajar $url ($($_.Exception.Message))" }
    Move-Item "$dest.part" $dest
}
$base = "https://github.com/alenj0x1/translay/releases/download/$Tag"
foreach ($f in "cpu.py", "podcast.mp4", "podcast.truth.json", "whisper-vulkan-x64.zip") { Get-File "$base/$f" (Join-Path $work $f) }
$wcpp = Join-Path $work "whisper-vulkan"
if (-not (Test-Path (Join-Path $wcpp "whisper-cli.exe"))) { Expand-Archive (Join-Path $work "whisper-vulkan-x64.zip") -DestinationPath $wcpp -Force }
$hf = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
Get-File "$hf/ggml-small.bin" (Join-Path $wcpp "ggml-small.bin")
Get-File "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin" (Join-Path $wcpp "ggml-silero-v5.1.2.bin")
if (-not $Quick) { Get-File "$hf/ggml-large-v3-turbo-q5_0.bin" (Join-Path $wcpp "ggml-large-v3-turbo-q5_0.bin") }

# ------------------------------------------------------------------ medir
$variants = @("stream-small-def", "stream-small-cores", "whole-small-def", "whole-small-cores", "batch-small-cores",
              "wcpp-small-cpu", "wcpp-small-vk", "mt-base-def", "mt-base-cores")
if (-not $Quick) { $variants += @("whole-turbo-cores", "batch-turbo-cores", "wcpp-turbo-vk") }
$out = Join-Path $work "out"
$env:TRANSLAY_CODE = $appCode
$env:PATH = "$tools;$env:PATH"  # ffmpeg de la app
$env:CUDA_VISIBLE_DEVICES = ""
$env:PYTHONIOENCODING = "utf-8"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$ErrorActionPreference = "Continue"  # en PowerShell 5, lo que Python escribe en stderr no debe cortar el lab
Say "Midiendo $($variants.Count) variantes × $Rounds rondas. No uses el equipo mientras tanto (la CPU tiene que estar libre)."
$started = Get-Date
& $python -u (Join-Path $work "cpu.py") --media (Join-Path $work "podcast.mp4") --out $out --cores $hw.cores `
    --rounds $Rounds --timeout 900 --whispercpp $wcpp --variants $variants 2>&1 | ForEach-Object { Say "$_" }
$rc = $LASTEXITCODE

# ------------------------------------------------------------------ juntar el resultado
$resFile = Join-Path $out "resultados.json"
$report = [ordered]@{ lab = $Tag; date = $stamp; hardware = $hw; quick = [bool]$Quick; exit_code = $rc
                      minutes = [math]::Round(((Get-Date) - $started).TotalMinutes, 1) }
if (Test-Path $resFile) { $report.results = Get-Content $resFile -Raw -Encoding UTF8 | ConvertFrom-Json }
$json = Join-Path $desk "translay-lab-$stamp.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $json -Encoding UTF8
if (-not $Keep) { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
Say "Listo en $($report.minutes) min. Envía estos dos archivos del Escritorio: $(Split-Path $json -Leaf) y $(Split-Path $log -Leaf)"
