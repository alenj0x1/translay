//! Translay as a desktop app: a native window around Translay's own web interface.
//! - First launch: the bundled setup page (ui/) installs Python, the server and the voice engine (runtime.rs).
//! - Every launch: starts the local server hidden (server.rs) and opens its page in the window.
//! - Custom title bar in both pages (the Windows one takes the system accent color instead of the theme's),
//!   with Windows 11 snap layouts on its maximize button (`snap_layouts`), tray icon when "Al cerrar la ventana" keeps Translay running (until the queue is empty), single instance.
//! - Tells about new versions and opens their download in the browser (updates.rs).

mod runtime;
mod server;
mod updates;

use runtime::{Paths, Settings};
use serde_json::{json, Value};
use server::Server;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

struct AppState {
    paths: Paths,
    settings: Mutex<Settings>,
    quitting: AtomicBool,
    /// The window was closed to the tray (not just minimized): the page may quit once the queue is empty.
    in_tray: AtomicBool,
}

impl AppState {
    fn settings(&self) -> Settings {
        self.settings.lock().unwrap().clone()
    }
}

/// Hardware, install state and the chosen library folder, for the setup screen.
#[tauri::command]
fn status(state: State<'_, AppState>) -> Value {
    runtime::status(&state.paths, &state.settings())
}

/// Installs what is missing (progress arrives as `setup` events). `voice`: the chosen profile has voice (saved);
/// without it, the last choice (or, from before profiles were chosen at setup, whenever the GPU can run it).
#[tauri::command]
async fn install(app: AppHandle, voice: Option<bool>) -> Result<(), String> {
    let state = app.state::<AppState>();
    let wants = {
        let mut settings = state.settings.lock().unwrap();
        if let Some(v) = voice {
            settings.voice = Some(v);
            settings.save(&state.paths)?;
        }
        settings.wants_voice(&runtime::detect_gpu())
    };
    runtime::install(app.clone(), &state.paths, wants).await
}

/// The profiles for the setup screen: the recommended one and how much each downloads (`vt.modelset profiles`).
#[tauri::command]
async fn profiles(state: State<'_, AppState>, data_dir: String) -> Result<Value, String> {
    runtime::profiles(&state.paths, std::path::Path::new(&data_dir)).await
}

/// Saves the chosen profile and downloads its models (progress as `setup` events, step "models").
#[tauri::command]
async fn prepare(app: AppHandle, data_dir: String, profile: String) -> Result<(), String> {
    let state = app.state::<AppState>();
    runtime::prepare(&app, &state.paths, std::path::Path::new(&data_dir), &profile).await
}

/// A profile with voice chosen inside Translay when the voice engine isn't installed: stops the server and goes
/// back to the setup screen, which installs it and opens Translay again.
#[tauri::command]
async fn reinstall(app: AppHandle, voice: bool) -> Result<(), String> {
    let state = app.state::<AppState>();
    {
        let mut settings = state.settings.lock().unwrap();
        settings.voice = Some(voice);
        settings.save(&state.paths)?;
    }
    app.state::<Server>().stop();
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.navigate(server::setup_url());
    }
    Ok(())
}

/// Confirms the library folder (first launch) and starts the server. `hold`: the first-run wizard is still open,
/// so the window stays on it when the server is ready (until `open_app`).
#[tauri::command]
async fn start(app: AppHandle, state: State<'_, AppState>, server: State<'_, Server>, data_dir: Option<String>, hold: Option<bool>) -> Result<(), String> {
    if let Some(dir) = data_dir {
        let mut settings = state.settings.lock().unwrap();
        settings.data_dir = Some(dir.into());
        settings.save(&state.paths)?;
    }
    server.hold(hold.unwrap_or(false));
    server.start(&app, &state.paths, &state.settings())
}

/// The first-run wizard finished: Translay opens now, or as soon as the server is ready.
#[tauri::command]
fn open_app(app: AppHandle, server: State<'_, Server>) {
    server.release(&app);
}

/// «Ver la bienvenida» (Ajustes › App de escritorio): the window goes back to the bundled page, which opens the
/// first-run wizard over what is already installed. The server keeps running; when the wizard ends, `open_app`
/// brings Translay back and its page applies what was changed (`take_welcome`).
#[tauri::command]
fn show_welcome(app: AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let mut url = server::setup_url();
        url.set_query(Some("welcome"));
        let _ = window.navigate(url);
    }
}

/// The first-run wizard saves what was chosen so far (also if the window closes halfway). Only plain data, at most
/// 8 KB; Translay's page reads it once (`take_welcome`).
#[tauri::command]
fn set_welcome(state: State<'_, AppState>, choices: Value) -> Result<(), String> {
    if !choices.is_object() || choices.to_string().len() > 8192 {
        return Err("Elecciones no válidas".into());
    }
    let mut settings = state.settings.lock().unwrap();
    settings.welcome = Some(choices);
    settings.save(&state.paths)
}

/// Translay's page, on its first load: what the first-run wizard chose (applied there through its own
/// preferences), then forgotten so it is applied only once.
#[tauri::command]
fn take_welcome(state: State<'_, AppState>) -> Result<Value, String> {
    let mut settings = state.settings.lock().unwrap();
    let Some(choices) = settings.welcome.take() else { return Ok(Value::Null) };
    settings.save(&state.paths)?;
    Ok(choices)
}

/// This computer's address on the local network (the wizard's «Desde el celular» step shows it). A UDP socket
/// "connected" to a public address only picks the route: nothing is sent.
#[tauri::command]
fn lan_ip() -> Option<String> {
    let socket = std::net::UdpSocket::bind("0.0.0.0:0").ok()?;
    socket.connect("192.0.2.1:80").ok()?;
    let ip = socket.local_addr().ok()?.ip();
    (!ip.is_loopback() && !ip.is_unspecified()).then(|| ip.to_string())
}

/// Lets the user pick another folder; returns it (or None if cancelled). Nothing is saved until `start`.
#[tauri::command]
async fn pick_folder(app: AppHandle) -> Option<String> {
    app.dialog()
        .file()
        .set_title("Dónde guardar tu biblioteca")
        .blocking_pick_folder()
        .and_then(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().to_string())
}

/// Desktop details for Translay's Preferences (App de escritorio).
#[tauri::command]
fn desktop_info(app: AppHandle, state: State<'_, AppState>) -> Value {
    let settings = state.settings();
    json!({
        "version": app.package_info().version.to_string(),
        "data_dir": settings.data_dir,
        "close_to_tray": settings.close_to_tray,
        "auto_update": settings.auto_update(),
        "logs": state.paths.logs(),
    })
}

/// Moves the main library to another folder: saves it and restarts the server there.
#[tauri::command]
async fn change_data_dir(app: AppHandle) -> Result<bool, String> {
    let Some(dir) = pick_folder(app.clone()).await else { return Ok(false) };
    let state = app.state::<AppState>();
    {
        let mut settings = state.settings.lock().unwrap();
        settings.data_dir = Some(dir.into());
        settings.save(&state.paths)?;
    }
    let server = app.state::<Server>();
    server.stop();
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.navigate(server::setup_url());
    }
    Ok(true)
}

/// Opens the library or the logs folder in the Explorer.
#[tauri::command]
fn open_folder(app: AppHandle, state: State<'_, AppState>, which: String) -> Result<(), String> {
    let path = match which.as_str() {
        "data" => state.settings().data_dir.ok_or("Sin carpeta de datos")?,
        "logs" => {
            let logs = state.paths.logs();
            std::fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
            logs
        }
        _ => return Err("Carpeta desconocida".into()),
    };
    app.opener().open_path(path.to_string_lossy(), None::<&str>).map_err(|e| e.to_string())
}

/// "Al cerrar la ventana": true keeps Translay (and its queue) running in the tray.
#[tauri::command]
fn set_close_to_tray(app: AppHandle, state: State<'_, AppState>, enabled: bool) -> Result<(), String> {
    {
        let mut settings = state.settings.lock().unwrap();
        if settings.close_to_tray != enabled {
            settings.close_to_tray = enabled;
            settings.save(&state.paths)?;
        }
    }
    sync_tray(&app, enabled).map_err(|e| e.to_string())
}

/// The title bar's close button: hides to the tray or quits, as chosen.
#[tauri::command]
fn close_window(app: AppHandle, state: State<'_, AppState>) {
    if state.settings().close_to_tray {
        if let Some(window) = app.get_webview_window("main") {
            state.in_tray.store(true, Ordering::SeqCst);
            let _ = window.hide();
        }
    } else {
        quit(&app);
    }
}

/// The page reports there is no work left: if the window is in the tray, quit and free every resource
/// (the server, its models and the voice process).
#[tauri::command]
fn quit_if_in_tray(app: AppHandle, state: State<'_, AppState>) {
    if state.in_tray.load(Ordering::SeqCst) {
        quit(&app);
    }
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    quit(&app);
}

fn quit(app: &AppHandle) {
    app.state::<AppState>().quitting.store(true, Ordering::SeqCst);
    app.state::<Server>().stop();
    app.exit(0);
}

/// Translay's page reports its theme (Ajustes › Apariencia) so the next launch opens in it.
#[tauri::command]
fn set_theme(app: AppHandle, state: State<'_, AppState>, theme: String) -> Result<(), String> {
    if theme != "light" && theme != "dark" {
        return Err("Tema desconocido".into());
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.set_background_color(Some(theme_background(&theme)));
    }
    let mut settings = state.settings.lock().unwrap();
    if settings.theme.as_deref() != Some(theme.as_str()) {
        settings.theme = Some(theme);
        settings.save(&state.paths)?;
    }
    Ok(())
}

/// Translay's page reports its accent color, background scene and language (Ajustes › Apariencia and Idioma),
/// so the startup screen of the next launch uses them. Unknown values are ignored, not stored.
#[tauri::command]
fn set_look(state: State<'_, AppState>, accent: String, scene: String, lang: String) -> Result<(), String> {
    let accent_ok = accent == "none" || (accent.len() == 7 && accent.starts_with('#') && accent[1..].chars().all(|c| c.is_ascii_hexdigit()));
    // scene names are words in Spanish («arañas y perro»): letters, spaces and dashes
    let scene_ok = !scene.is_empty() && scene.chars().count() <= 32 && scene.chars().all(|c| c.is_alphanumeric() || c == ' ' || c == '_' || c == '-');
    if !accent_ok || !scene_ok || !["es", "en", "pt"].contains(&lang.as_str()) {
        return Err("Apariencia desconocida".into());
    }
    let mut settings = state.settings.lock().unwrap();
    let next = (Some(accent), Some(scene), Some(lang));
    if (settings.accent.clone(), settings.scene.clone(), settings.lang.clone()) != next {
        (settings.accent, settings.scene, settings.lang) = next;
        settings.save(&state.paths)?;
    }
    Ok(())
}

/// Window background before the page paints (web/css/tokens.css: --bg).
fn theme_background(theme: &str) -> tauri::window::Color {
    if theme == "light" { tauri::window::Color(0xf8, 0xf8, 0xf9, 0xff) } else { tauri::window::Color(0x16, 0x16, 0x16, 0xff) }
}

/// The main window, created here (not in tauri.conf.json) so it opens with the saved look: the setup page
/// reads `window.__TRANSLAY_THEME__` and `window.__TRANSLAY_LOOK__` (accent, scene, language) before its first paint.
fn create_window(app: &tauri::App, settings: &Settings) -> tauri::Result<()> {
    let theme = settings.theme.as_deref();
    let look = serde_json::json!({ "accent": settings.accent, "scene": settings.scene, "lang": settings.lang });
    let mut script = format!("window.__TRANSLAY_LOOK__ = {look};");
    if let Some(t) = theme {
        script += &format!("window.__TRANSLAY_THEME__ = {};", serde_json::to_string(t).unwrap());
    }
    let mut builder = tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::App("index.html".into()))
        .title("Translay")
        .inner_size(1320.0, 840.0)
        .min_inner_size(960.0, 620.0)
        .decorations(false)
        .shadow(false)
        .center()
        .background_color(theme_background(theme.unwrap_or("dark")));
    builder = builder.initialization_script(&script);
    builder.build()?;
    Ok(())
}

/// Windows 11 snap layouts for the custom maximize button: the system only shows them over its own caption
/// button, so the page asks for them (hovering or holding "Maximizar") and this opens them as Win+Z does.
/// Returns false where they do not exist (Windows 10), so the page stops asking.
#[tauri::command]
fn snap_layouts(app: AppHandle) -> bool {
    #[cfg(windows)]
    {
        use windows_sys::Wdk::System::SystemServices::RtlGetVersion;
        use windows_sys::Win32::System::SystemInformation::OSVERSIONINFOW;
        use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
            SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VIRTUAL_KEY, VK_LWIN,
        };
        // SAFETY: plain struct filled by the OS; size set as the API requires.
        let build = unsafe {
            let mut v: OSVERSIONINFOW = std::mem::zeroed();
            v.dwOSVersionInfoSize = std::mem::size_of::<OSVERSIONINFOW>() as u32;
            if RtlGetVersion(&mut v) != 0 {
                return false;
            }
            v.dwBuildNumber
        };
        if build < 22000 {
            return false;
        }
        if let Some(window) = app.get_webview_window("main") {
            if window.is_maximized().unwrap_or(false) || !window.is_focused().unwrap_or(false) {
                let _ = window.set_focus();
            }
        }
        let key = |vk: VIRTUAL_KEY, up: bool| INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 { ki: KEYBDINPUT { wVk: vk, wScan: 0, dwFlags: if up { KEYEVENTF_KEYUP } else { 0 }, time: 0, dwExtraInfo: 0 } },
        };
        const VK_Z: VIRTUAL_KEY = 0x5A;
        let inputs = [key(VK_LWIN, false), key(VK_Z, false), key(VK_Z, true), key(VK_LWIN, true)];
        // SAFETY: a valid array of keyboard inputs with its element size.
        unsafe { SendInput(inputs.len() as u32, inputs.as_ptr(), std::mem::size_of::<INPUT>() as i32) };
        true
    }
    #[cfg(not(windows))]
    {
        let _ = app;
        false
    }
}

/// Last lines of the server output, for the error screen.
#[tauri::command]
fn server_tail(server: State<'_, Server>) -> Vec<String> {
    server.tail()
}

fn show_main(app: &AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        state.in_tray.store(false, Ordering::SeqCst);
    }
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

const TRAY_ID: &str = "main";

fn sync_tray(app: &AppHandle, enabled: bool) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
    if !enabled {
        app.remove_tray_by_id(TRAY_ID);
        return Ok(());
    }
    if app.tray_by_id(TRAY_ID).is_some() {
        return Ok(());
    }
    let show = MenuItem::with_id(app, "show", "Abrir Translay", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Salir", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &quit_item])?;
    let mut tray = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("Translay")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main(app),
            "quit" => quit(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // A second launch (Start menu while Translay is in the tray) brings back the open window.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(Server::default())
        .setup(|app| {
            let paths = Paths::resolve(app)?;
            let settings = Settings::load(&paths);
            let tray = settings.close_to_tray;
            create_window(app, &settings)?;
            app.manage(AppState { paths, settings: Mutex::new(settings), quitting: AtomicBool::new(false), in_tray: AtomicBool::new(false) });
            sync_tray(app.handle(), tray)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let state = app.state::<AppState>();
                if state.quitting.load(Ordering::SeqCst) {
                    return;
                }
                if state.settings().close_to_tray {
                    api.prevent_close();
                    state.in_tray.store(true, Ordering::SeqCst);
                    let _ = window.hide();
                } else {
                    app.state::<Server>().stop();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            status, install, profiles, prepare, reinstall, start, pick_folder, desktop_info, change_data_dir, open_folder, set_close_to_tray,
            close_window, quit_app, quit_if_in_tray, server_tail, set_theme, set_look, snap_layouts,
            open_app, set_welcome, take_welcome, show_welcome, lan_ip,
            updates::open_download, updates::set_auto_update
        ])
        .build(tauri::generate_context!())
        .expect("failed to start Translay");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            app.state::<Server>().stop();
        }
    });
}
