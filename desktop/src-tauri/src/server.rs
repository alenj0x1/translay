//! Translay's local server (`run.py`) in a hidden process, owned by the window:
//! - It runs inside a Windows job object that kills the whole tree (voice worker, ffmpeg, yt-dlp…) when the
//!   app quits or crashes.
//! - Its output feeds the loading screen ("Preparando large-v3-turbo…", model downloads) and `logs/server.log`.
//! - When it prints "Listo: http://…" the window opens that page, with IPC allowed only for that exact origin.
//! - "Reiniciar ahora" (Preferencias › Rendimiento) restarts the server from inside: the new process stays in
//!   the job and inherits the output pipe, so the output only ends when every server process is gone.

use crate::runtime::{Paths, Settings, CREATE_NO_WINDOW};
use serde_json::json;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncRead, BufReader};
use tokio::process::Command;

#[cfg(windows)]
mod job {
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};

    pub struct Job(HANDLE);
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        pub fn new() -> Option<Self> {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if handle.is_null() {
                    return None;
                }
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                Some(Job(handle))
            }
        }

        pub fn assign(&self, pid: u32) -> bool {
            unsafe {
                let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
                if process.is_null() {
                    return false;
                }
                let ok = AssignProcessToJobObject(self.0, process) != 0;
                CloseHandle(process);
                ok
            }
        }

        pub fn kill(&self) {
            unsafe {
                TerminateJobObject(self.0, 1);
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[derive(Default)]
pub struct Server {
    job: Mutex<Option<job::Job>>,
    /// Incremented on every start/stop: output from an older server never touches the window.
    generation: AtomicU64,
    url: Mutex<Option<String>>,
    tail: Mutex<Vec<String>>,
}

/// First free port from 8765 (Translay's usual one) so the page keeps its saved state between launches.
fn free_port() -> Result<u16, String> {
    (8765..8865)
        .chain(std::iter::once(0))
        .find_map(|port| std::net::TcpListener::bind(("127.0.0.1", port)).ok())
        .and_then(|l| l.local_addr().ok())
        .map(|a| a.port())
        .ok_or_else(|| "No hay un puerto libre para el servidor.".to_string())
}

pub fn setup_url() -> tauri::Url {
    "http://tauri.localhost/index.html".parse().unwrap()
}

impl Server {
    pub fn url(&self) -> Option<String> {
        self.url.lock().unwrap().clone()
    }

    pub fn tail(&self) -> Vec<String> {
        self.tail.lock().unwrap().clone()
    }

    pub fn stop(&self) {
        self.generation.fetch_add(1, Ordering::SeqCst);
        *self.url.lock().unwrap() = None;
        if let Some(job) = self.job.lock().unwrap().take() {
            job.kill();
        }
    }

    pub fn start(&self, app: &AppHandle, paths: &Paths, settings: &Settings) -> Result<(), String> {
        self.stop();
        let generation = self.generation.load(Ordering::SeqCst);
        let data = settings.data_dir.clone().ok_or("Elige dónde guardar tu biblioteca.")?;
        std::fs::create_dir_all(&data).map_err(|e| format!("No se pudo crear la carpeta de datos: {e}"))?;
        std::fs::create_dir_all(paths.logs()).map_err(|e| e.to_string())?;
        let port = free_port()?;
        self.tail.lock().unwrap().clear();

        // ffmpeg, ffprobe and node (yt-dlp's JavaScript runtime) from the bundled tools, ahead of the PATH.
        let path = std::env::var_os("PATH").unwrap_or_default();
        let mut dirs = vec![paths.tools.clone()];
        dirs.extend(std::env::split_paths(&path));
        let path = std::env::join_paths(dirs).map_err(|e| e.to_string())?;

        let mut cmd = Command::new(paths.server_python());
        cmd.arg("-u")
            .arg(paths.code.join("run.py"))
            .args(["--no-browser", "--port", &port.to_string(), "--data-dir"])
            .arg(&data)
            .current_dir(&paths.code)
            .env("PATH", path)
            .env("TRANSLAY_VENVS", paths.venvs())
            .env("TRANSLAY_DESKTOP", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH")
            .env_remove("VIRTUAL_ENV")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .creation_flags(CREATE_NO_WINDOW);
        let mut child = cmd.spawn().map_err(|e| format!("No se pudo iniciar el servidor de Translay: {e}"))?;
        let job = job::Job::new();
        if let (Some(job), Some(pid)) = (&job, child.id()) {
            job.assign(pid);
        }
        *self.job.lock().unwrap() = job;

        let log = paths.logs().join("server.log");
        let _ = std::fs::write(&log, "");
        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let out = pump(app.clone(), Box::new(stdout), log.clone(), generation);
        let err = pump(app.clone(), Box::new(stderr), log, generation);
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            // The original process may exit while a restarted one keeps the pipes open: wait for both pipes.
            let _ = child.wait().await;
            let _ = tokio::join!(out, err);
            let server = app.state::<Server>();
            if server.generation.load(Ordering::SeqCst) != generation {
                return; // stopped on purpose (quit, data folder changed)
            }
            server.stop();
            let _ = app.emit("server", json!({ "state": "error", "tail": server.tail() }));
            if let Some(window) = app.get_webview_window("main") {
                if window.url().map(|u| u.host_str() != Some("tauri.localhost")).unwrap_or(true) {
                    let mut url = setup_url();
                    url.set_query(Some("error=1"));
                    let _ = window.navigate(url);
                }
            }
        });
        Ok(())
    }

    fn on_line(&self, app: &AppHandle, line: &str, generation: u64) {
        if self.generation.load(Ordering::SeqCst) != generation {
            return;
        }
        {
            let mut tail = self.tail.lock().unwrap();
            tail.push(line.to_string());
            if tail.len() > 40 {
                tail.remove(0);
            }
        }
        if let Some(url) = line.strip_prefix("Listo: ") {
            let url = url.trim().to_string();
            if self.url().is_none() {
                *self.url.lock().unwrap() = Some(url.clone());
                open_page(app, &url);
            }
            return;
        }
        let _ = app.emit("server", json!({ "state": "starting", "line": line }));
    }
}

/// Lets the Translay page (exact origin) use the window controls and the desktop commands, then opens it.
fn open_page(app: &AppHandle, url: &str) {
    use tauri::ipc::CapabilityBuilder;
    let origin = url.trim_end_matches('/');
    let capability = CapabilityBuilder::new(format!("server-{}", origin.rsplit(':').next().unwrap_or("0")))
        .remote(format!("{origin}/*"))
        .window("main")
        .permission("core:event:default")
        .permission("core:window:allow-start-dragging")
        .permission("core:window:allow-minimize")
        .permission("core:window:allow-toggle-maximize")
        .permission("core:window:allow-is-maximized")
        .permission("core:window:allow-hide")
        .permission("allow-desktop-info")
        .permission("allow-change-data-dir")
        .permission("allow-open-folder")
        .permission("allow-set-close-to-tray")
        .permission("allow-close-window")
        .permission("allow-set-theme")
        .permission("allow-quit-if-in-tray");
    let _ = app.add_capability(capability);
    let _ = app.emit("server", json!({ "state": "ready", "url": url }));
    if let (Some(window), Ok(parsed)) = (app.get_webview_window("main"), url.parse()) {
        let _ = window.navigate(parsed);
    }
}

/// Reads one output pipe; tqdm progress bars (model downloads) rewrite their line with `\r`.
fn pump(app: AppHandle, reader: Box<dyn AsyncRead + Unpin + Send>, log: PathBuf, generation: u64) -> tauri::async_runtime::JoinHandle<()> {
    tauri::async_runtime::spawn(async move {
        let mut reader = BufReader::new(reader);
        let mut buf = Vec::new();
        loop {
            buf.clear();
            match reader.read_until(b'\n', &mut buf).await {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
            let text = String::from_utf8_lossy(&buf).to_string();
            append(&log, &text);
            for part in text.split('\r') {
                let line = part.trim();
                if !line.is_empty() {
                    app.state::<Server>().on_line(&app, line, generation);
                }
            }
        }
    })
}

fn append(path: &PathBuf, text: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = f.write_all(text.as_bytes());
    }
}
