//! Live subtitles over any window: a strip at the bottom of the screen with the live translation of whatever the
//! computer is playing (video calls, games, streams).
//! - Audio: WASAPI loopback of the default output device, in its own thread, mixed to mono and resampled to
//!   16 kHz int16; 100 ms chunks go to the strip's page through a Tauri channel (raw bytes). Silence (nothing
//!   playing: loopback delivers no packets) is filled with zeros so the timeline stays continuous. A change of
//!   default device (headphones plugged in) reopens the capture.
//! - Window: transparent, undecorated, always on top, not in the taskbar, never activated, click-through. It loads
//!   `live.html` from Translay's server; the page opens an ephemeral session on /ws (nothing is saved) and draws
//!   the latest lines.
//! - Moving it: a watcher thread follows the cursor (GetCursorPos, every 30 ms). Over the strip, the page shows a
//!   grip at its left edge; only over that grip the window takes the mouse (the page then drags the window).
//!   Everywhere else clicks go to the window behind. The position is saved once the strip stops moving.
//! - Stays on top: the watcher re-asserts TOPMOST every 2 s without activating it (another topmost window that
//!   opened later would otherwise cover it).

use crate::runtime::Paths;
use crate::AppState;
use serde_json::json;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::ipc::{Channel, InvokeResponseBody};
use tauri::{AppHandle, Emitter, Manager, State};

pub const LABEL: &str = "live";
const SR: u32 = 16_000;
const CHUNK: usize = 1600; // 100 ms
/// Strip size in logical pixels: two lines of text at the page's size (web/live.html).
const MAX_WIDTH: f64 = 1100.0;
const HEIGHT: f64 = 128.0;
/// Gap between the strip and the bottom of the work area (above the taskbar).
const BOTTOM_GAP: f64 = 40.0;

#[derive(Default)]
pub struct Live {
    /// Incremented when the strip closes or a new capture starts: older capture threads stop.
    capture: std::sync::Arc<AtomicU64>,
    /// Incremented on every open: the watcher of an older strip stops.
    watcher: AtomicU64,
    /// The grip's rectangle (CSS pixels, relative to the window), reported by the page.
    grip: Mutex<[f64; 4]>,
}

/// Opens (`on`) or closes the strip. Returns whether it is open. The main page shows the state on its button.
/// Async: creating a window from a sync command deadlocks on Windows.
#[tauri::command]
pub async fn live_set(app: AppHandle, on: bool) -> Result<bool, String> {
    if on {
        open(&app)?;
    } else {
        close(&app);
    }
    Ok(on)
}

#[tauri::command]
pub fn live_state(app: AppHandle) -> bool {
    app.get_webview_window(LABEL).is_some()
}

/// The strip's page asks for the audio: every chunk arrives as raw bytes (int16 LE mono 16 kHz).
#[tauri::command]
pub fn live_audio(app: AppHandle, live: State<'_, Live>, on_audio: Channel<InvokeResponseBody>) {
    let my = live.capture.fetch_add(1, Ordering::SeqCst) + 1;
    let gen = live.capture.clone();
    std::thread::Builder::new()
        .name("live-capture".into())
        .spawn(move || capture::run(app, gen, my, on_audio))
        .ok();
}

/// Where the grip is (CSS pixels inside the window): only there the strip takes the mouse.
#[tauri::command]
pub fn live_grip(live: State<'_, Live>, x: f64, y: f64, w: f64, h: f64) {
    *live.grip.lock().unwrap() = [x, y, w, h];
}

/// The page painted: show the strip without taking the focus from the window the person is using.
#[tauri::command]
pub fn live_shown(app: AppHandle) {
    if let Some(window) = app.get_webview_window(LABEL) {
        // Tauri's show (not a bare ShowWindow): it also shows the webview's own windows, without which the strip is
        // drawn but the mouse never reaches it (the grip couldn't be dragged). The window is not focusable, so tao
        // shows it without activating it; if the system activated it anyway, the focus goes back.
        let before = win::foreground();
        let _ = window.show();
        if let Ok(hwnd) = window.hwnd() {
            let hwnd = hwnd.0 as isize;
            win::keep_on_top(hwnd);
            if win::foreground() == hwnd && before != 0 && before != hwnd {
                win::set_foreground(before);
            }
        }
    }
}

pub fn open(app: &AppHandle) -> Result<(), String> {
    if app.get_webview_window(LABEL).is_some() {
        return Ok(());
    }
    let base = app.state::<crate::server::Server>().url().ok_or("Translay aún no está listo.")?;
    let url: tauri::Url = format!("{}/live.html", base.trim_end_matches('/')).parse().map_err(|e| format!("{e}"))?;
    crate::server::allow_live(app, &base);

    // the monitor of Translay's window (or the primary one)
    let monitor = app
        .get_webview_window("main")
        .and_then(|w| w.current_monitor().ok().flatten())
        .or_else(|| app.primary_monitor().ok().flatten())
        .ok_or("No se encontró la pantalla.")?;
    let scale = monitor.scale_factor();
    let area = *monitor.work_area();
    let width = (area.size.width as f64 / scale * 0.72).min(MAX_WIDTH);
    let (pw, ph) = ((width * scale) as i32, (HEIGHT * scale) as i32);
    let default = [
        area.position.x + (area.size.width as i32 - pw) / 2,
        area.position.y + area.size.height as i32 - ph - (BOTTOM_GAP * scale) as i32,
    ];
    let saved = app.state::<AppState>().settings().live_pos;
    // a saved place on a screen that is no longer there (or partly off-screen): back to the default
    let pos = saved.filter(|p| app.available_monitors().map(|ms| ms.iter().any(|m| fits(m, *p, pw, ph))).unwrap_or(false)).unwrap_or(default);

    let window = tauri::WebviewWindowBuilder::new(app, LABEL, tauri::WebviewUrl::External(url))
        .title("Translay")
        .inner_size(width, HEIGHT)
        .decorations(false)
        .transparent(true)
        .no_redirection_bitmap(true)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .focused(false)
        .focusable(false)
        .visible(false)
        .build()
        .map_err(|e| e.to_string())?;
    let _ = window.set_position(tauri::PhysicalPosition::new(pos[0], pos[1]));
    let _ = window.set_ignore_cursor_events(true);
    let hwnd = window.hwnd().map_err(|e| e.to_string())?.0 as isize;
    let live = app.state::<Live>();
    let my = live.watcher.fetch_add(1, Ordering::SeqCst) + 1;
    *live.grip.lock().unwrap() = [0.0; 4];
    let app2 = app.clone();
    std::thread::Builder::new().name("live-watch".into()).spawn(move || watch(app2, hwnd, my, pos)).ok();
    let _ = app.emit_to("main", "live", json!({ "on": true }));
    Ok(())
}

fn fits(m: &tauri::Monitor, p: [i32; 2], w: i32, h: i32) -> bool {
    let a = m.work_area();
    let (x0, y0) = (a.position.x, a.position.y);
    let (x1, y1) = (x0 + a.size.width as i32, y0 + a.size.height as i32);
    p[0] >= x0 - w / 2 && p[0] + w <= x1 + w / 2 && p[1] >= y0 && p[1] + h <= y1
}

pub fn close(app: &AppHandle) {
    let live = app.state::<Live>();
    live.capture.fetch_add(1, Ordering::SeqCst);
    live.watcher.fetch_add(1, Ordering::SeqCst);
    if let Some(window) = app.get_webview_window(LABEL) {
        let _ = window.destroy();
        let _ = app.emit_to("main", "live", json!({ "on": false }));
    }
}

/// Follows the cursor (grip → takes the mouse; elsewhere → click-through), tells the page when the cursor is
/// over the strip (it shows the grip), keeps the strip on top and saves where it was left.
fn watch(app: AppHandle, hwnd: isize, my: u64, mut saved: [i32; 2]) {
    let mut over = false;
    let mut grabbing = false;
    let mut moved_at: Option<Instant> = None;
    let mut last_pos = saved;
    let mut last_top = Instant::now();
    loop {
        std::thread::sleep(Duration::from_millis(30));
        if app.state::<Live>().watcher.load(Ordering::SeqCst) != my || !win::is_window(hwnd) {
            return;
        }
        let Some((rect, cursor, scale)) = win::geometry(hwnd) else { continue };
        let inside = |x0: f64, y0: f64, x1: f64, y1: f64| {
            (cursor.0 as f64) >= x0 && (cursor.0 as f64) < x1 && (cursor.1 as f64) >= y0 && (cursor.1 as f64) < y1
        };
        let now_over = inside(rect[0] as f64, rect[1] as f64, rect[2] as f64, rect[3] as f64);
        if now_over != over {
            over = now_over;
            let _ = app.emit_to(LABEL, "live-hover", json!({ "over": over }));
        }
        let g = *app.state::<Live>().grip.lock().unwrap();
        let (gx, gy) = (rect[0] as f64 + g[0] * scale, rect[1] as f64 + g[1] * scale);
        let on_grip = over && g[2] > 0.0 && inside(gx, gy, gx + g[2] * scale, gy + g[3] * scale);
        if on_grip != grabbing {
            grabbing = on_grip;
            let app2 = app.clone();
            // window calls belong to the main thread; nothing is locked here
            let _ = app.run_on_main_thread(move || {
                if let Some(w) = app2.get_webview_window(LABEL) {
                    let _ = w.set_ignore_cursor_events(!on_grip);
                }
            });
        }
        let pos = [rect[0], rect[1]];
        if pos != last_pos {
            last_pos = pos;
            moved_at = Some(Instant::now());
        } else if moved_at.is_some_and(|t| t.elapsed() > Duration::from_millis(600)) && pos != saved {
            moved_at = None;
            saved = pos;
            save_pos(&app, pos);
        }
        if last_top.elapsed() > Duration::from_secs(2) && !grabbing {
            last_top = Instant::now();
            win::keep_on_top(hwnd);
        }
    }
}

fn save_pos(app: &AppHandle, pos: [i32; 2]) {
    let state = app.state::<AppState>();
    let paths: &Paths = &state.paths;
    let mut settings = state.settings.lock().unwrap();
    settings.live_pos = Some(pos);
    let _ = settings.save(paths);
}

/// Mono, 16 kHz: a box filter over each output sample's span of input (enough for speech recognition).
pub struct Resampler {
    ratio: f64,
    pos: f64,
    buf: Vec<f32>,
}

impl Resampler {
    pub fn new(rate: u32) -> Self {
        Resampler { ratio: rate as f64 / SR as f64, pos: 0.0, buf: Vec::new() }
    }

    pub fn push(&mut self, mono: &[f32], out: &mut Vec<i16>) {
        self.buf.extend_from_slice(mono);
        let half = (self.ratio / 2.0).max(0.5);
        while self.pos + half < self.buf.len() as f64 {
            let a = (self.pos - half).max(0.0).floor() as usize;
            let b = ((self.pos + half).ceil() as usize).min(self.buf.len()).max(a + 1);
            let v = self.buf[a..b].iter().sum::<f32>() / (b - a) as f32;
            out.push((v.clamp(-1.0, 1.0) * 32767.0) as i16);
            self.pos += self.ratio;
        }
        let drop = ((self.pos - half).floor().max(0.0) as usize).min(self.buf.len());
        self.buf.drain(..drop);
        self.pos -= drop as f64;
    }
}

mod capture {
    use super::{Resampler, CHUNK, LABEL, SR};
    use serde_json::json;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Arc;
    use std::time::{Duration, Instant};
    use tauri::ipc::{Channel, InvokeResponseBody};
    use tauri::{AppHandle, Emitter};
    use windows::Win32::Media::Audio::{
        eConsole, eRender, IAudioCaptureClient, IAudioClient, IMMDeviceEnumerator, MMDeviceEnumerator,
        AUDCLNT_BUFFERFLAGS_SILENT, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK, WAVEFORMATEX,
        WAVEFORMATEXTENSIBLE,
    };
    use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, CoTaskMemFree, CLSCTX_ALL, COINIT_MULTITHREADED};

    struct Out {
        ch: Channel<InvokeResponseBody>,
        pcm: Vec<i16>,
        sent: u64,
        start: Instant,
        last_data: Instant,
    }

    impl Out {
        fn flush(&mut self) -> bool {
            while self.pcm.len() >= CHUNK {
                let bytes: Vec<u8> = self.pcm.drain(..CHUNK).flat_map(|s| s.to_le_bytes()).collect();
                self.sent += CHUNK as u64;
                if self.ch.send(InvokeResponseBody::Raw(bytes)).is_err() {
                    return false;
                }
            }
            true
        }

        /// Nothing playing: loopback sends no packets, so silence keeps the timeline (100 ms behind real time).
        fn pad(&mut self) {
            if self.last_data.elapsed() < Duration::from_millis(250) {
                return;
            }
            let target = (self.start.elapsed().as_secs_f64() * SR as f64) as u64;
            let have = self.sent + self.pcm.len() as u64;
            if target > have + CHUNK as u64 {
                self.pcm.extend(std::iter::repeat(0).take((target - have - CHUNK as u64) as usize));
            }
        }
    }

    pub fn run(app: AppHandle, gen: Arc<AtomicU64>, my: u64, ch: Channel<InvokeResponseBody>) {
        // SAFETY: COM for this thread only.
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }
        let now = Instant::now();
        let mut out = Out { ch, pcm: Vec::new(), sent: 0, start: now, last_data: now };
        let mut reported = String::new();
        while gen.load(Ordering::SeqCst) == my {
            match session(&gen, my, &mut out) {
                Ok(true) => return, // stopped, or the page is gone
                Ok(false) => {}     // default device changed: reopen
                Err(e) => {
                    let msg = e.to_string();
                    if msg != reported {
                        reported = msg.clone();
                        let _ = app.emit_to(LABEL, "live-error", json!({ "message": format!("captura de audio: {msg}") }));
                    }
                    // keep the timeline going while the device is unavailable
                    for _ in 0..10 {
                        std::thread::sleep(Duration::from_millis(100));
                        out.pad();
                        if !out.flush() {
                            return;
                        }
                    }
                }
            }
        }
    }

    fn default_id(en: &IMMDeviceEnumerator) -> windows::core::Result<String> {
        // SAFETY: COM calls on an initialized enumerator; the id string is freed after copying it.
        unsafe {
            let device = en.GetDefaultAudioEndpoint(eRender, eConsole)?;
            let id = device.GetId()?;
            let s = id.to_string().unwrap_or_default();
            CoTaskMemFree(Some(id.0 as _));
            Ok(s)
        }
    }

    /// One capture of the default output device. Ok(true): stop for good; Ok(false): the default device changed.
    fn session(gen: &AtomicU64, my: u64, out: &mut Out) -> windows::core::Result<bool> {
        // SAFETY: plain WASAPI use: every pointer comes from the API and is used while valid.
        unsafe {
            let en: IMMDeviceEnumerator = CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)?;
            let device = en.GetDefaultAudioEndpoint(eRender, eConsole)?;
            let id = default_id(&en)?;
            let client: IAudioClient = device.Activate(CLSCTX_ALL, None)?;
            let fmt = client.GetMixFormat()?;
            let f: WAVEFORMATEX = std::ptr::read_unaligned(fmt);
            let (tag, channels, rate, bits) = (f.wFormatTag, f.nChannels as usize, f.nSamplesPerSec, f.wBitsPerSample);
            let float = tag == 3
                || (tag == 0xFFFE && std::ptr::read_unaligned(fmt as *const WAVEFORMATEXTENSIBLE).SubFormat.data1 == 3);
            let init = client.Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK, 2_000_000, 0, fmt, None);
            CoTaskMemFree(Some(fmt as _));
            init?;
            if channels == 0 || !(float && bits == 32 || !float && (bits == 16 || bits == 32)) {
                return Err(windows::core::Error::new(windows::core::HRESULT(0x88890008u32 as i32), "formato de audio no compatible"));
            }
            let cap: IAudioCaptureClient = client.GetService()?;
            client.Start()?;
            let mut rs = Resampler::new(rate);
            let mut mono: Vec<f32> = Vec::new();
            let mut checked = Instant::now();
            let result = loop {
                if gen.load(Ordering::SeqCst) != my {
                    break Ok(true);
                }
                let mut packet = cap.GetNextPacketSize()?;
                while packet > 0 {
                    let mut data: *mut u8 = std::ptr::null_mut();
                    let mut frames = 0u32;
                    let mut flags = 0u32;
                    cap.GetBuffer(&mut data, &mut frames, &mut flags, None, None)?;
                    let n = frames as usize;
                    mono.clear();
                    if flags & (AUDCLNT_BUFFERFLAGS_SILENT.0 as u32) != 0 || data.is_null() {
                        mono.resize(n, 0.0);
                    } else if float {
                        let s = std::slice::from_raw_parts(data as *const f32, n * channels);
                        mono.extend(s.chunks_exact(channels).map(|c| c.iter().sum::<f32>() / channels as f32));
                    } else if bits == 16 {
                        let s = std::slice::from_raw_parts(data as *const i16, n * channels);
                        mono.extend(s.chunks_exact(channels).map(|c| c.iter().map(|&v| v as f32).sum::<f32>() / (channels as f32 * 32768.0)));
                    } else {
                        let s = std::slice::from_raw_parts(data as *const i32, n * channels);
                        mono.extend(s.chunks_exact(channels).map(|c| c.iter().map(|&v| v as f32).sum::<f32>() / (channels as f32 * 2147483648.0)));
                    }
                    cap.ReleaseBuffer(frames)?;
                    rs.push(&mono, &mut out.pcm);
                    out.last_data = Instant::now();
                    packet = cap.GetNextPacketSize()?;
                }
                out.pad();
                if !out.flush() {
                    break Ok(true);
                }
                if checked.elapsed() > Duration::from_secs(1) {
                    checked = Instant::now();
                    if default_id(&en).map(|d| d != id).unwrap_or(true) {
                        break Ok(false);
                    }
                }
                std::thread::sleep(Duration::from_millis(10));
            };
            let _ = client.Stop();
            result
        }
    }
}

/// Raw Win32 reads and non-blocking placement (fine from any thread).
mod win {
    use windows_sys::Win32::Foundation::{HWND, POINT, RECT};
    use windows_sys::Win32::UI::HiDpi::GetDpiForWindow;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetCursorPos, GetForegroundWindow, GetWindowRect, IsWindow, SetForegroundWindow, SetWindowPos, HWND_TOPMOST,
        SWP_ASYNCWINDOWPOS, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE,
    };

    fn h(hwnd: isize) -> HWND {
        hwnd as HWND
    }

    pub fn is_window(hwnd: isize) -> bool {
        // SAFETY: IsWindow accepts any value.
        unsafe { IsWindow(h(hwnd)) != 0 }
    }

    /// Window rectangle and cursor (physical pixels) and the window's scale.
    pub fn geometry(hwnd: isize) -> Option<([i32; 4], (i32, i32), f64)> {
        // SAFETY: out-parameters filled by the OS.
        unsafe {
            let mut r: RECT = std::mem::zeroed();
            let mut p: POINT = std::mem::zeroed();
            if GetWindowRect(h(hwnd), &mut r) == 0 || GetCursorPos(&mut p) == 0 {
                return None;
            }
            let dpi = GetDpiForWindow(h(hwnd));
            Some(([r.left, r.top, r.right, r.bottom], (p.x, p.y), if dpi == 0 { 1.0 } else { dpi as f64 / 96.0 }))
        }
    }

    pub fn keep_on_top(hwnd: isize) {
        // SAFETY: z-order only, asynchronous: a busy UI thread never blocks the caller.
        unsafe {
            SetWindowPos(h(hwnd), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
        }
    }

    pub fn foreground() -> isize {
        // SAFETY: plain read.
        unsafe { GetForegroundWindow() as isize }
    }

    pub fn set_foreground(hwnd: isize) {
        // SAFETY: gives the focus back to the window that had it (this process is in front at that moment).
        unsafe {
            SetForegroundWindow(h(hwnd));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::Resampler;

    #[test]
    fn resamples_48k_to_16k() {
        let mut rs = Resampler::new(48_000);
        let mut out = Vec::new();
        let tone: Vec<f32> = (0..48_000).map(|i| (i as f32 * 440.0 * std::f32::consts::TAU / 48_000.0).sin() * 0.5).collect();
        for part in tone.chunks(480) {
            rs.push(part, &mut out);
        }
        assert!((15_990..=16_000).contains(&out.len()), "{}", out.len());
        let peak = out.iter().map(|v| v.unsigned_abs()).max().unwrap();
        assert!(peak > 14_000 && peak < 16_500, "{peak}");
    }

    #[test]
    fn resamples_44k1_to_16k() {
        let mut rs = Resampler::new(44_100);
        let mut out = Vec::new();
        for part in vec![0.25f32; 44_100].chunks(441) {
            rs.push(part, &mut out);
        }
        assert!((15_990..=16_000).contains(&out.len()), "{}", out.len());
        assert!(out.iter().all(|&v| (v - 8191).abs() <= 1));
    }
}
