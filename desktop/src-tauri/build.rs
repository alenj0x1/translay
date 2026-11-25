// Declaring the app commands generates one permission per command (allow-<name>): the setup page gets
// all of them (capabilities/default.json) and Translay's page only the ones it uses (server.rs).
const COMMANDS: &[&str] = &[
    "status", "install", "profiles", "prepare", "reinstall", "start", "pick_folder", "desktop_info", "change_data_dir", "open_folder", "set_close_to_tray",
    "close_window", "quit_app", "quit_if_in_tray", "server_tail", "set_theme", "set_look",
    "open_download", "set_auto_update", "open_app", "set_welcome", "take_welcome", "show_welcome", "lan_ip",
    "live_set", "live_state", "live_audio", "live_grip", "live_shown",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("Tauri build script failed");
}
