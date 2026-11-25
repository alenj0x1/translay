# UI Automation de la app de escritorio para tests/e2e/desktop.py (solo lectura: busca, no hace clic).
#   pwsh -File uia.ps1 windows <pid>          ventanas de primer nivel del proceso: hwnd, visible, rectángulo, título
#   pwsh -File uia.ps1 find <pid> <id|nombre> el elemento con ese AutomationId (o ese nombre) en la ventana principal:
#                                             su rectángulo en píxeles de pantalla, o nada
#   pwsh -File uia.ps1 names <pid>            los nombres de los botones de la ventana principal
# Salida: JSON en una línea. Una lectura que falla (el árbol se está rehaciendo) da [] / null, no un error.
param([string]$Mode, [int]$ProcessId, [string]$Target = "")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

function Get-Tops([int]$procId) {
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $procId)
  [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
}

function Get-Main([int]$procId) {
  # la ventana principal: la visible más grande (la franja de subtítulos es baja y ancha)
  $best = $null; $area = 0
  foreach ($w in (Get-Tops $procId)) {
    $r = $w.Current.BoundingRectangle
    if ($w.Current.IsOffscreen -or $r.IsEmpty) { continue }
    $a = $r.Width * $r.Height
    if ($a -gt $area -and $r.Height -gt 300) { $best = $w; $area = $a }
  }
  $best
}

try {
  switch ($Mode) {
    "windows" {
      $out = foreach ($w in (Get-Tops $ProcessId)) {
        $r = $w.Current.BoundingRectangle
        [pscustomobject]@{ hwnd = $w.Current.NativeWindowHandle; visible = -not $w.Current.IsOffscreen; title = $w.Current.Name
                           x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height }
      }
      ConvertTo-Json -Compress -InputObject @($out)
    }
    "find" {
      $main = Get-Main $ProcessId
      if (-not $main) { "null"; break }
      $byId = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $Target)
      $byName = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $Target)
      $either = New-Object System.Windows.Automation.OrCondition($byId, $byName)
      $e = $main.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $either)
      if (-not $e) { "null"; break }
      $r = $e.Current.BoundingRectangle
      ConvertTo-Json -Compress -InputObject ([pscustomobject]@{ name = $e.Current.Name; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height
                                                                 main = $main.Current.NativeWindowHandle })
    }
    "names" {
      $main = Get-Main $ProcessId
      if (-not $main) { "[]"; break }
      $btn = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
      $names = foreach ($e in $main.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btn)) { $e.Current.Name }
      ConvertTo-Json -Compress -InputObject @($names | Where-Object { $_ })
    }
  }
} catch {
  if ($Mode -eq "find") { "null" } else { "[]" }
}
