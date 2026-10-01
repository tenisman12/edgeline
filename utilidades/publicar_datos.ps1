# Publica tus datos actuales en la rama "datos" de GitHub (una sola version, sin historial).
# Uso (PowerShell):
#     cd C:\Edgeline_repo
#     powershell -ExecutionPolicy Bypass -File utilidades\publicar_datos.ps1
# Que hace:
#   1. recorta tus jugadores a los ultimos 60 dias (datos\jugadores_recientes) con las columnas que usa la pagina
#   2. copia datos\ (sin jugadores completos ni _respaldo) a C:\Edgeline_pub
#   3. revisa que ningun archivo pase de 90 MB (GitHub rechaza mas de 100 MB)
#   4. sube todo como un solo commit a la rama datos
param(
    [string]$Repo = "C:\Edgeline_repo",
    [string]$Pub  = "C:\Edgeline_pub",
    [string]$Remoto = "https://github.com/tenisman12/edgeline.git"
)
$ErrorActionPreference = "Stop"
Set-Location $Repo
$env:EDGELINE_BASE = $Repo

Write-Host "1/4 Recortando jugadores recientes ..."
python utilidades\jugadores_recientes.py recortar

Write-Host "2/4 Copiando datos a $Pub ..."
if (Test-Path $Pub) { Remove-Item $Pub -Recurse -Force }
New-Item -ItemType Directory -Path "$Pub\datos" | Out-Null
robocopy "$Repo\datos" "$Pub\datos" /E /XD jugadores _respaldo /NFL /NDL /NJH /NJS | Out-Null

Write-Host "3/4 Revisando tamanos ..."
$grandes = Get-ChildItem $Pub -Recurse -File | Where-Object { $_.Length -gt 90MB }
if ($grandes) {
    $grandes | Select-Object FullName, @{n='MB';e={[int]($_.Length/1MB)}} | Format-Table -AutoSize
    throw "Hay archivos de mas de 90 MB. No se sube nada."
}
$n = (Get-ChildItem $Pub -Recurse -File).Count
$mb = [int]((Get-ChildItem $Pub -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ("    {0} archivos, {1} MB" -f $n, $mb)

Write-Host "4/4 Subiendo a la rama datos ..."
Set-Location $Pub
git init -b datos | Out-Null
git add -A
git commit -q -m ("datos " + (Get-Date -Format "yyyy-MM-dd HH:mm"))
git remote add origin $Remoto
git push -f origin datos
Set-Location $Repo
Write-Host "Listo."
