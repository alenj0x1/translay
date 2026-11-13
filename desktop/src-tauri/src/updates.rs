//! New versions (Ajustes › App de escritorio): the server finds them (vt/updates.py) and the page shows
//! them; here only the settings and opening the download in the default browser. The app never downloads
//! or runs an installer itself: an app that does that is what Windows Defender's machine-learning scan
//! mistook for a trojan, so the person runs the installer from the browser as usual.

use crate::AppState;
use tauri::{AppHandle, State};
use tauri_plugin_opener::OpenerExt;

/// Only Translay's GitHub releases can be opened from here.
const RELEASES: &str = "https://github.com/alenj0x1/translay/releases/";

#[tauri::command]
pub fn open_download(app: AppHandle, url: String) -> Result<(), String> {
    if !url.starts_with(RELEASES) || url.contains("..") {
        return Err("Esa dirección no es una versión de Translay".into());
    }
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_auto_update(state: State<'_, AppState>, enabled: bool) -> Result<(), String> {
    let mut settings = state.settings.lock().unwrap();
    if settings.auto_update() != enabled {
        settings.check_updates = Some(enabled);
        settings.save(&state.paths)?;
    }
    Ok(())
}
