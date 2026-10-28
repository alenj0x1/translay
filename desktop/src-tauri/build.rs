// Declaring the app commands generates one permission per command (allow-<name>): the setup page gets
// all of them (capabilities/default.json) and Translay's page only the ones it uses (server.rs).
const COMMANDS: &[&str] = &[
    "status", "install", "start", "pick_folder", "desktop_info", "change_data_dir", "open_folder", "set_close_to_tray",
    "close_window", "quit_app", "quit_if_in_tray", "server_tail", "set_theme",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("Tauri build script failed");
}
