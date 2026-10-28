//! The runtime Translay needs, installed by the app itself on first launch (no manual steps):
//! - The server packages (`locks/server.txt`) in `<app data>/runtime/server`, on the bundled Python 3.12.
//! - The voice engine (OmniVoice on CUDA, `locks/voice.txt`) in `<app data>/runtime/venvs/omnivoice`, on the
//!   bundled Python 3.11, only when the GPU can run it.
//! Both Pythons ship in the installer (python-build-standalone, verified by scripts/prepare.mjs): uv 0.13's own
//! Python downloads fail under some user folders. Packages come from the bundled `uv` with pinned versions and
//! SHA-256 hashes (`--require-hashes`);
//! `uv pip sync` installs exactly the lock (no dependency resolution on the user's machine).
//! A lock that changes in a new version is synced again on the next launch.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Minimum VRAM for the lightest profile with cloned voice (vt/profiles.py, labs in data/labs).
const VOICE_MIN_VRAM_MB: u64 = 3800;

/// Bytes each step downloads into the uv cache, measured on a clean install: drives the progress bar.
const SERVER_BYTES: u64 = 1_900_000_000;
const VOICE_BYTES: u64 = 5_500_000_000;

pub struct Paths {
    /// `<LocalAppData>/dev.alejandro.translay`: runtime, logs and settings (removed by the uninstaller if asked).
    pub base: PathBuf,
    /// Translay's code (vt/, web/, run.py).
    pub code: PathBuf,
    pub locks: PathBuf,
    /// uv, ffmpeg, ffprobe and node (fetched and verified by scripts/prepare.mjs).
    pub tools: PathBuf,
    /// Default library folder: `<Videos>/Translay` (outside the app data, so uninstalling never deletes videos).
    pub default_data: PathBuf,
}

impl Paths {
    pub fn resolve(app: &tauri::App) -> Result<Self, String> {
        let path = app.path();
        let base = path.app_local_data_dir().map_err(|e| e.to_string())?;
        let default_data = path
            .video_dir()
            .or_else(|_| path.home_dir())
            .map_err(|e| e.to_string())?
            .join("Translay");
        #[cfg(debug_assertions)]
        let (code, locks, tools) = {
            let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            (manifest.join("..").join(".."), manifest.join("..").join("locks"), manifest.join("tools"))
        };
        #[cfg(not(debug_assertions))]
        let (code, locks, tools) = {
            let res = without_verbatim(path.resource_dir().map_err(|e| e.to_string())?);
            (res.join("translay"), res.join("locks"), res.join("tools"))
        };
        Ok(Self { base, code, locks, tools, default_data })
    }

    pub fn runtime(&self) -> PathBuf {
        self.base.join("runtime")
    }
    pub fn logs(&self) -> PathBuf {
        self.base.join("logs")
    }
    pub fn server_python(&self) -> PathBuf {
        self.runtime().join("server").join("Scripts").join("python.exe")
    }
    pub fn venvs(&self) -> PathBuf {
        self.runtime().join("venvs")
    }
    fn voice_python(&self) -> PathBuf {
        self.venvs().join("omnivoice").join("Scripts").join("python.exe")
    }
    fn state_file(&self) -> PathBuf {
        self.runtime().join("state.json")
    }
    fn settings_file(&self) -> PathBuf {
        self.base.join("desktop.json")
    }
}

/// Strips the `\\?\` prefix Tauri leaves on the resource folder: Python and uv reject some of those paths.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn without_verbatim(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = text.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path
    }
}

#[derive(Serialize, Deserialize, Default, Clone)]
pub struct Settings {
    /// Folder of the main library (Translay's `--data-dir`). None until the user confirms it on the setup screen.
    pub data_dir: Option<PathBuf>,
    /// Keep running in the tray when the window closes (the queue keeps processing).
    #[serde(default)]
    pub close_to_tray: bool,
    /// Last theme Translay showed ("light" or "dark"): the setup and loading screens open with it.
    #[serde(default)]
    pub theme: Option<String>,
}

impl Settings {
    pub fn load(paths: &Paths) -> Self {
        std::fs::read_to_string(paths.settings_file())
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }
    pub fn save(&self, paths: &Paths) -> Result<(), String> {
        std::fs::create_dir_all(&paths.base).map_err(|e| e.to_string())?;
        write_atomic(&paths.settings_file(), &serde_json::to_string_pretty(self).unwrap())
    }
}

fn write_atomic(path: &Path, text: &str) -> Result<(), String> {
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, text).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

fn lock_hash(path: &Path) -> String {
    let bytes = std::fs::read(path).unwrap_or_default();
    format!("{:x}", Sha256::digest(bytes))
}

fn read_state(paths: &Paths) -> Value {
    std::fs::read_to_string(paths.state_file())
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| json!({}))
}

fn mark_installed(paths: &Paths, key: &str, lock: &Path) -> Result<(), String> {
    let mut state = read_state(paths);
    state[key] = json!(lock_hash(lock));
    write_atomic(&paths.state_file(), &state.to_string())
}

fn installed(paths: &Paths, key: &str, python: &Path, lock: &Path) -> bool {
    python.exists() && read_state(paths)[key] == json!(lock_hash(lock))
}

#[derive(Serialize, Clone)]
pub struct Gpu {
    pub name: String,
    /// None when the driver reports no dedicated memory (unified memory, e.g. DGX Spark).
    pub vram_mb: Option<u64>,
}

/// NVIDIA GPU through nvidia-smi (installed with the driver in System32).
pub fn detect_gpu() -> Option<Gpu> {
    use std::os::windows::process::CommandExt;
    let system_root = std::env::var("SystemRoot").unwrap_or_else(|_| r"C:\Windows".into());
    let exe = PathBuf::from(system_root).join("System32").join("nvidia-smi.exe");
    let out = std::process::Command::new(exe)
        .args(["--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&out.stdout);
    let line = text.lines().next()?.trim();
    let (name, mem) = line.rsplit_once(',')?;
    Some(Gpu { name: name.trim().to_string(), vram_mb: mem.trim().parse().ok() })
}

pub fn voice_supported(gpu: &Option<Gpu>) -> bool {
    match gpu {
        Some(Gpu { vram_mb: Some(mb), .. }) => *mb >= VOICE_MIN_VRAM_MB,
        Some(Gpu { vram_mb: None, .. }) => true, // unified memory: the voice runs from system RAM
        None => false,
    }
}

pub fn status(paths: &Paths, settings: &Settings) -> Value {
    let gpu = detect_gpu();
    let voice = voice_supported(&gpu);
    let server_ok = installed(paths, "server", &paths.server_python(), &paths.locks.join("server.txt"));
    let voice_ok = !voice || installed(paths, "voice", &paths.voice_python(), &paths.locks.join("voice.txt"));
    json!({
        "version": env!("CARGO_PKG_VERSION"),
        "gpu": gpu,
        "voice": voice,
        "server_ok": server_ok,
        "voice_ok": voice_ok,
        "ready": server_ok && voice_ok && settings.data_dir.is_some(),
        "data_dir": settings.data_dir.clone().unwrap_or_else(|| paths.default_data.clone()),
        "data_chosen": settings.data_dir.is_some(),
        "first_run": !paths.server_python().exists(),
    })
}

/// Size of a folder in bytes (the uv cache grows as packages download: that is the progress).
fn dir_size(path: &Path) -> u64 {
    let mut total = 0;
    let mut stack = vec![path.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let Ok(meta) = entry.metadata() else { continue };
            if meta.is_dir() {
                stack.push(entry.path());
            } else {
                total += meta.len();
            }
        }
    }
    total
}

pub static INSTALLING: AtomicBool = AtomicBool::new(false);

struct Step {
    key: &'static str,
    weight: f64,
    bytes: u64,
}

/// Installs whatever is missing, emitting `setup` events: {step, state, percent, done_bytes, total_bytes, error?}.
pub async fn install(app: AppHandle, paths: &Paths) -> Result<(), String> {
    if INSTALLING.swap(true, Ordering::SeqCst) {
        return Err("La instalación ya está en curso.".into());
    }
    let result = run_install(&app, paths).await;
    INSTALLING.store(false, Ordering::SeqCst);
    if let Err(e) = &result {
        let _ = app.emit("setup", json!({ "state": "error", "error": e }));
    }
    result
}

async fn run_install(app: &AppHandle, paths: &Paths) -> Result<(), String> {
    let voice = voice_supported(&detect_gpu());
    let server_lock = paths.locks.join("server.txt");
    let voice_lock = paths.locks.join("voice.txt");
    let need_server = !installed(paths, "server", &paths.server_python(), &server_lock);
    let need_voice = voice && !installed(paths, "voice", &paths.voice_python(), &voice_lock);

    let mut steps = Vec::new();
    if need_server {
        steps.push(Step { key: "server", weight: 0.30, bytes: SERVER_BYTES });
    }
    if need_voice {
        steps.push(Step { key: "voice", weight: 0.70, bytes: VOICE_BYTES });
    }
    let total_weight: f64 = steps.iter().map(|s| s.weight).sum();
    let total_bytes: u64 = steps.iter().map(|s| s.bytes).sum();
    std::fs::create_dir_all(paths.logs()).map_err(|e| e.to_string())?;
    let log = paths.logs().join("setup.log");
    let _ = std::fs::write(&log, "");

    let mut done_weight = 0.0;
    let mut done_bytes = 0u64;
    for step in &steps {
        let ctx = Progress { app, step: step.key, base: done_weight / total_weight, span: step.weight / total_weight,
            bytes: step.bytes, done_bytes, total_bytes };
        ctx.emit(0.0, "running");
        match step.key {
            "server" => {
                let venv = paths.runtime().join("server");
                if !paths.server_python().exists() {
                    let python = paths.tools.join("python-3.12").join("python.exe");
                    uv(paths, &["venv", "--python", &python.to_string_lossy(), &venv.to_string_lossy()], &log, &ctx).await?;
                }
                uv(paths, &["pip", "sync", "--require-hashes", "--python", &paths.server_python().to_string_lossy(),
                    &server_lock.to_string_lossy()], &log, &ctx).await?;
                mark_installed(paths, "server", &server_lock)?;
            }
            "voice" => {
                let venv = paths.venvs().join("omnivoice");
                if !paths.voice_python().exists() {
                    let python = paths.tools.join("python-3.11").join("python.exe");
                    uv(paths, &["venv", "--python", &python.to_string_lossy(), &venv.to_string_lossy()], &log, &ctx).await?;
                }
                uv(paths, &["pip", "sync", "--require-hashes", "--torch-backend", "cu128", "--python",
                    &paths.voice_python().to_string_lossy(), &voice_lock.to_string_lossy()], &log, &ctx).await?;
                mark_installed(paths, "voice", &voice_lock)?;
            }
            _ => unreachable!(),
        }
        ctx.emit(1.0, "done");
        done_weight += step.weight;
        done_bytes += step.bytes;
    }
    let _ = app.emit("setup", json!({ "state": "finished", "percent": 100 }));
    Ok(())
}

struct Progress<'a> {
    app: &'a AppHandle,
    step: &'static str,
    base: f64,
    span: f64,
    bytes: u64,
    done_bytes: u64,
    total_bytes: u64,
}

impl Progress<'_> {
    fn emit(&self, fraction: f64, state: &str) {
        let fraction = fraction.clamp(0.0, 1.0);
        let _ = self.app.emit("setup", json!({
            "step": self.step,
            "state": state,
            "percent": ((self.base + self.span * fraction) * 100.0).floor(),
            "done_bytes": self.done_bytes + (self.bytes as f64 * fraction) as u64,
            "total_bytes": self.total_bytes,
        }));
    }
}

/// Runs the bundled uv with its own Python and cache folders (nothing from the user's uv or Python is used).
async fn uv(paths: &Paths, args: &[&str], log: &Path, ctx: &Progress<'_>) -> Result<(), String> {
    let runtime = paths.runtime();
    let cache = runtime.join("cache");
    std::fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    let mut cmd = Command::new(paths.tools.join("uv.exe"));
    cmd.args(args)
        .env("UV_CACHE_DIR", &cache)
        .env("UV_PYTHON_DOWNLOADS", "never")
        .env("UV_NO_CONFIG", "1")
        .env("UV_NO_PROGRESS", "1")
        .env("UV_LINK_MODE", "hardlink")
        .env_remove("VIRTUAL_ENV")
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW)
        .kill_on_drop(true);
    let mut child = cmd.spawn().map_err(|e| format!("No se pudo iniciar uv: {e}"))?;
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();

    let log_path = log.to_path_buf();
    let header = format!("$ uv {}\n", args.join(" "));
    append(&log_path, &header);
    let tail = std::sync::Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
    let pump = |reader: Box<dyn tokio::io::AsyncRead + Unpin + Send>| {
        let log_path = log_path.clone();
        let tail = tail.clone();
        tokio::spawn(async move {
            let mut lines = BufReader::new(reader).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                append(&log_path, &format!("{line}\n"));
                let mut t = tail.lock().unwrap();
                t.push(line);
                if t.len() > 12 {
                    t.remove(0);
                }
            }
        })
    };
    let a = pump(Box::new(stdout));
    let b = pump(Box::new(stderr));

    let measure = || dir_size(&cache);
    let start = measure();
    let status = loop {
        tokio::select! {
            status = child.wait() => break status.map_err(|e| e.to_string())?,
            _ = tokio::time::sleep(Duration::from_millis(1500)) => {
                let grown = measure().saturating_sub(start);
                ctx.emit((grown as f64 / ctx.bytes as f64).min(0.97), "running");
            }
        }
    };
    let _ = tokio::join!(a, b);
    if status.success() {
        Ok(())
    } else {
        let last = tail.lock().unwrap().iter().rev().find(|l| !l.trim().is_empty()).cloned().unwrap_or_default();
        Err(format!("La instalación se detuvo ({}). {}", status.code().map(|c| format!("código {c}")).unwrap_or_default(), last.trim()))
    }
}

fn append(path: &Path, text: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = f.write_all(text.as_bytes());
    }
}

