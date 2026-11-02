//! Updates from inside the app (Preferencias › App de escritorio): looks for a newer version on GitHub,
//! downloads it and installs it. Every download is checked against the public key built into the app
//! (tauri.conf.json › plugins.updater.pubkey), so only installers signed with Translay's key are accepted.
//!
//! - `check_update`: asks the release feed (latest.json of the latest GitHub release); returns the version
//!   and its notes, or `available: false`.
//! - `install_update`: downloads the found version (progress as `update` events), stops the server and runs
//!   the installer, which closes Translay, updates it and opens it again.
//! - `set_auto_update`: the page checks by itself on launch and every few hours unless this is off.
//!
//! The feed isn't signed, but each installer's signature carries its version (`requireSignedVersion`): a
//! tampered feed can't pass an older, genuinely signed installer off as a newer version.
//!
//! Test builds only (cargo feature `update-url-override`): TRANSLAY_UPDATE_URL replaces the feed; it must
//! be https unless that build also turns on `dangerousInsecureTransportProtocol`. The signature check
//! never changes.

use crate::server::Server;
use crate::AppState;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Default)]
pub struct Updates {
    found: Mutex<Option<Update>>,
    /// A download or install is running: a second request is refused (no double download).
    busy: AtomicBool,
}

fn updater(app: &AppHandle) -> Result<tauri_plugin_updater::Updater, String> {
    #[allow(unused_mut)]
    let mut builder = app.updater_builder();
    #[cfg(feature = "update-url-override")]
    if let Ok(url) = std::env::var("TRANSLAY_UPDATE_URL") {
        let parsed: tauri::Url = url.parse().map_err(|_| "TRANSLAY_UPDATE_URL no es una dirección válida".to_string())?;
        builder = builder.endpoints(vec![parsed]).map_err(|e| e.to_string())?;
    }
    // una conexión que se queda quieta no deja la descarga colgada para siempre
    builder
        .configure_client(|c| c.connect_timeout(std::time::Duration::from_secs(30)).read_timeout(std::time::Duration::from_secs(60)))
        .restart_after_install(true)
        .build()
        .map_err(|e| e.to_string())
}

/// Plain words for the page (never the plugin's raw error).
fn friendly(e: impl std::fmt::Display) -> String {
    let text = e.to_string();
    if text.contains("signature") || text.contains("Signature") {
        "La actualización descargada no tiene la firma de Translay; se descartó.".into()
    } else if text.contains("error sending request") || text.contains("dns") || text.contains("connect") {
        "No se pudo conectar para buscar actualizaciones. Revisa la conexión a internet.".into()
    } else {
        format!("No se pudo actualizar: {text}")
    }
}

#[tauri::command]
pub async fn check_update(app: AppHandle, updates: State<'_, Updates>) -> Result<Value, String> {
    let current = app.package_info().version.to_string();
    let found = updater(&app)?.check().await.map_err(friendly)?;
    let out = match &found {
        Some(u) => json!({ "available": true, "current": current, "version": u.version, "notes": u.body, "date": u.date.map(|d| d.to_string()) }),
        None => json!({ "available": false, "current": current }),
    };
    *updates.found.lock().unwrap() = found;
    Ok(out)
}

#[tauri::command]
pub async fn install_update(app: AppHandle, updates: State<'_, Updates>) -> Result<(), String> {
    let update = updates.found.lock().unwrap().clone().ok_or("Primero busca actualizaciones")?;
    if updates.busy.swap(true, Ordering::SeqCst) {
        return Err("La actualización ya se está descargando".into());
    }
    let result = download_and_install(&app, update).await;
    updates.busy.store(false, Ordering::SeqCst);
    result
}

async fn download_and_install(app: &AppHandle, update: Update) -> Result<(), String> {
    let progress = app.clone();
    let mut done: u64 = 0;
    let mut last: Option<u64> = None; // un aviso por punto porcentual, no por bloque (~10 000 en 120 MB)
    let bytes = update
        .download(
            move |chunk, total| {
                done += chunk as u64;
                let pct = total.map(|t| (done * 100 / t.max(1)).min(100));
                if pct != last || (pct.is_none() && done % (8 << 20) < chunk as u64) {
                    last = pct;
                    let _ = progress.emit("update", json!({ "state": "downloading", "pct": pct, "mb": done >> 20 }));
                }
            },
            || {},
        )
        .await
        .map_err(friendly)?;
    let _ = app.emit("update", json!({ "state": "installing" }));
    // the installer replaces the app's files: the server (and its models) must not be holding them
    let state = app.state::<AppState>();
    state.quitting.store(true, Ordering::SeqCst);
    app.state::<Server>().stop();
    if let Err(e) = update.install(bytes) {
        // on Windows a successful install exits here; if it failed, Translay keeps working as before
        state.quitting.store(false, Ordering::SeqCst);
        let _ = app.state::<Server>().start(app, &state.paths, &state.settings());
        return Err(friendly(e));
    }
    Ok(())
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
