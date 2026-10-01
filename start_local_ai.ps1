# Start the local AI server only when its loopback endpoint is unavailable.
$ErrorActionPreference='Stop'
try { $null=Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3; exit 0 } catch {}
$adrianOllama=Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $adrianOllama)) { throw 'Install Ollama before starting local AI.' }
$env:OLLAMA_LLM_LIBRARY='vulkan'
$env:GGML_VK_VISIBLE_DEVICES='0'
$env:OLLAMA_VULKAN='1'
$env:OLLAMA_NO_CLOUD='1'
$env:OLLAMA_HOST='127.0.0.1:11434'
$env:OLLAMA_NUM_PARALLEL='1'
$env:OLLAMA_MAX_LOADED_MODELS='1'
$env:OLLAMA_CONTEXT_LENGTH='8192'
Start-Process -FilePath $adrianOllama -ArgumentList 'serve' -WindowStyle Hidden
