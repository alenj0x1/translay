//! Translay as a desktop app: a native window around Translay's own web interface.
//! - First launch: the bundled setup page (ui/) installs Python, the server and the voice engine (runtime.rs).
//! - Every launch: starts the local server hidden (server.rs) and opens its page in the window.
//! - Custom title bar in both pages (the Windows one takes the system accent color instead of the theme's),
//!   tray icon when "Al cerrar la ventana" keeps Translay running, single instance.

mod runtime;
mod server;

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

/// Installs what is missing (progress arrives as `setup` events).
#[tauri::command]
async fn install(app: AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    runtime::install(app.clone(), &state.paths).await
}

/// Confirms the library folder (first launch) and starts the server.
#[tauri::command]
async fn start(app: AppHandle, state: State<'_, AppState>, server: State<'_, Server>, data_dir: Option<String>) -> Result<(), String> {
    if let Some(dir) = data_dir {
        let mut settings = state.settings.lock().unwrap();
        settings.data_dir = Some(dir.into());
        settings.save(&state.paths)?;
    }
    server.start(&app, &state.paths, &state.settings())
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
fn desktop_info(state: State<'_, AppState>) -> Value {
    let settings = state.settings();
    json!({
        "version": env!("CARGO_PKG_VERSION"),
        "data_dir": settings.data_dir,
        "close_to_tray": settings.close_to_tray,
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
            let _ = window.hide();
        }
    } else {
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

/// Translay's page reports its theme (Preferencias › Apariencia) so the next launch opens in it.
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

/// Window background before the page paints (web/css/tokens.css: --bg).
fn theme_background(theme: &str) -> tauri::window::Color {
    if theme == "light" { tauri::window::Color(0xf3, 0xf4, 0xf6, 0xff) } else { tauri::window::Color(0x18, 0x19, 0x1c, 0xff) }
}

/// The main window, created here (not in tauri.conf.json) so it opens with the saved theme: the setup page
/// reads `window.__TRANSLAY_THEME__` before its first paint.
fn create_window(app: &tauri::App, theme: Option<&str>) -> tauri::Result<()> {
    let script = match theme {
        Some(t) => format!("window.__TRANSLAY_THEME__ = {};", serde_json::to_string(t).unwrap()),
        None => String::new(),
    };
    let mut builder = tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::App("index.html".into()))
        .title("Translay")
        .inner_size(1320.0, 840.0)
        .min_inner_size(960.0, 620.0)
        .decorations(false)
        .shadow(false)
        .center()
        .background_color(theme_background(theme.unwrap_or("dark")));
    if !script.is_empty() {
        builder = builder.initialization_script(&script);
    }
    builder.build()?;
    Ok(())
}

/// Last lines of the server output, for the error screen.
#[tauri::command]
fn server_tail(server: State<'_, Server>) -> Vec<String> {
    server.tail()
}

fn show_main(app: &AppHandle) {
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
            create_window(app, settings.theme.as_deref())?;
            app.manage(AppState { paths, settings: Mutex::new(settings), quitting: AtomicBool::new(false) });
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
                    let _ = window.hide();
                } else {
                    app.state::<Server>().stop();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            status, install, start, pick_folder, desktop_info, change_data_dir, open_folder, set_close_to_tray,
            close_window, quit_app, server_tail, set_theme
        ])
        .build(tauri::generate_context!())
        .expect("failed to start Translay");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            app.state::<Server>().stop();
        }
    });
}
